import base64
import io
import json
import os
import re
from typing import Optional

import httpx
from dotenv import load_dotenv
from llama_cloud import LlamaCloud
from pydantic import BaseModel, Field

try:
	import fitz  # PyMuPDF
except Exception:
	fitz = None

try:
	from PIL import Image
except Exception:
	Image = None

try:
	import pytesseract
except Exception:
	pytesseract = None

load_dotenv()


class NutritionLabel(BaseModel):
	name: str = Field(min_length=1)
	category: str | None = None
	calories: float = Field(ge=0)
	protein: float = Field(ge=0)
	carbs: float = Field(ge=0)
	fats: float = Field(ge=0)
	serving_size: str | None = None


_CATALOG_ROW = re.compile(
	r"^\s*(?P<name>.+?)\s+"
	r"(?P<calories>\d+(?:\.\d+)?)\s+"
	r"(?P<fats>\d+(?:\.\d+)?)\s+"
	r"\d+(?:\.\d+)?\s+"
	r"\d+(?:\.\d+)?\s+"
	r"\d+(?:\.\d+)?\s+"
	r"\d+(?:\.\d+)?\s+"
	r"(?P<carbs>\d+(?:\.\d+)?)\s+"
	r"\d+(?:\.\d+)?\s+"
	r"\d+(?:\.\d+)?\s+"
	r"(?P<protein>\d+(?:\.\d+)?)\s*$"
)


def extract_nutrition_catalog(label_text: str) -> list[NutritionLabel]:
	"""Extract all nutrition rows from a LlamaParse-rendered catalog table."""
	rows = []
	lines = label_text.splitlines()
	category = None
	line_index = 0
	while line_index < len(lines):
		line = lines[line_index].strip()
		if line and not _CATALOG_ROW.match(line) and line.lower() != "menu item":
			if not line.startswith("©") and "Canadian Edition" not in line:
				category = re.sub(r"\s+", " ", line)
		match = _CATALOG_ROW.match(line)
		if not match:
			line_index += 1
			continue

		name = match.group("name").strip()
		if name.lower() == "menu item":
			line_index += 1
			continue
		if name.endswith("-") and line_index + 1 < len(lines):
			continuation = lines[line_index + 1].strip()
			if continuation and not _CATALOG_ROW.match(continuation):
				name = f"{name} {continuation}".strip()
				line_index += 1

		rows.append(NutritionLabel(
			name=re.sub(r"\s+", " ", name),
			category=category,
			calories=float(match.group("calories")),
			protein=float(match.group("protein")),
			carbs=float(match.group("carbs")),
			fats=float(match.group("fats")),
		))
		line_index += 1
	return rows


def extract_nutrition_catalog_from_pdf(pdf_bytes: bytes) -> list[NutritionLabel]:
	if not fitz:
		raise RuntimeError("PyMuPDF is required for image-based catalog extraction")

	page_images = []
	try:
		doc = fitz.open(stream=pdf_bytes, filetype="pdf")
	except Exception:
		return []
	try:
		for page in doc:
			pix = page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5), alpha=False)
			page_images.append({
				"type": "image_url",
				"image_url": {
					"url": f"data:image/jpeg;base64,{base64.b64encode(pix.tobytes('jpeg', jpg_quality=35)).decode('ascii')}"
				},
			})
	finally:
		doc.close()

	prompt = (
		"Extract every menu item and its nutrition values from these PDF page images. "
		"Return only JSON in this shape: {\"items\":[{\"name\":string,"
		"\"calories\":number,\"protein\":number,\"carbs\":number,"
		"\"fats\":number,\"serving_size\":string|null,\"category\":string|null}]}. "
		"Use values per serving. Do not invent items or values."
	)
	items = []
	for image in page_images:
		try:
			result = _extract_label_json({
				"messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, image]}],
				"max_tokens": 4_000,
				"model": os.getenv("LLAMA_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"),
			})
		except httpx.HTTPStatusError as exc:
			raise RuntimeError(
				"The configured vision model is unavailable. Set LLAMA_VISION_MODEL "
				"to a vision-capable model enabled by your provider."
			) from exc
		items.extend(result.get("items", []))
	return [NutritionLabel.model_validate(item) for item in items]


def _extract_label(payload: dict) -> NutritionLabel:
	return NutritionLabel.model_validate(_extract_label_json(payload))


def _extract_label_json(payload: dict) -> dict:
	api_key = os.getenv("LLAMA_API_KEY")
	base_url = os.getenv("LLAMA_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
	model = os.getenv("LLAMA_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
	if not api_key:
		raise RuntimeError("LLAMA_API_KEY is not configured")

	payload.setdefault("model", model)
	payload["temperature"] = 0
	payload["response_format"] = {"type": "json_object"}
	with httpx.Client(timeout=60) as client:
		response = client.post(
			f"{base_url}/chat/completions",
			headers={"Authorization": f"Bearer {api_key}"},
			json=payload,
		)
		if response.status_code == 400 and "response_format" in payload:
			fallback_payload = {key: value for key, value in payload.items() if key != "response_format"}
			response = client.post(
				f"{base_url}/chat/completions",
				headers={"Authorization": f"Bearer {api_key}"},
				json=fallback_payload,
			)
		response.raise_for_status()

	content = response.json()["choices"][0]["message"]["content"].strip()
	if content.startswith("```"):
		content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
	return json.loads(content)


def extract_nutrition_label(label_text: str) -> NutritionLabel:
	prompt = (
		"Parse this nutrition label and return only valid JSON with these keys: "
		"name, calories, protein, carbs, fats, serving_size. "
		"Use numeric values per serving for the four nutrition fields. "
		"Use null for serving_size if it is not provided.\n\n"
		f"Nutrition label:\n{label_text}"
	)
	return _extract_label({"messages": [{"role": "user", "content": prompt}]})


def extract_nutrition_label_from_image(image: bytes, content_type: str) -> NutritionLabel:
	prompt = (
		"Read this nutrition label image and return only valid JSON with these keys: "
		"name, calories, protein, carbs, fats, serving_size. "
		"Use numeric values per serving for the four nutrition fields. "
		"Use null for serving_size if it is not visible."
	)
	data_url = f"data:{content_type};base64,{base64.b64encode(image).decode('ascii')}"
	return _extract_label({
		"messages": [{
			"role": "user",
			"content": [
				{"type": "text", "text": prompt},
				{"type": "image_url", "image_url": {"url": data_url}},
			],
		}],
	})


def parse_pdf(pdf_bytes: bytes, filename: str) -> str:
	api_key = os.getenv("LLAMA_CLOUD_API_KEY")
	if not api_key:
		raise RuntimeError("LLAMA_CLOUD_API_KEY is not configured")

	client = LlamaCloud(api_key=api_key)
	try:
		result = client.parsing.parse(
			tier="cost_effective",
			version="latest",
			upload_file=(filename, pdf_bytes, "application/pdf"),
			expand=["text"],
		)
		content = result.text_full or result.text or result.markdown_full or result.markdown
		if isinstance(content, str):
			return content.strip()
		if content and hasattr(content, "pages"):
			return "\n".join(page.text for page in content.pages if page.text).strip()
		text = ""
		if content:
			# fallback generic string coercion
			try:
				text = str(content)
			except Exception:
				text = ""
		if text:
			return text.strip()
		# final fallback: attempt a local OCR pass if available
		ocr_text = _local_ocr_from_pdf(pdf_bytes)
		return ocr_text or ""
	finally:
		client.close()


def _local_ocr_from_pdf(pdf_bytes: bytes) -> str:
	"""Attempt local OCR using PyMuPDF + pytesseract as a fallback.

	This is best-effort: it requires PyMuPDF and pytesseract to be installed
	and for the system `tesseract` binary to be available. If any piece is
	missing we return an empty string so the caller can handle it.
	"""
	if not fitz or not pytesseract or not Image:
		return ""

	texts = []
	try:
		doc = fitz.open(stream=pdf_bytes, filetype="pdf")
	except Exception:
		return ""

	for page in doc:
		try:
			mat = fitz.Matrix(2.0, 2.0)
			pix = page.get_pixmap(matrix=mat, alpha=False)
			img_bytes = pix.tobytes("png")
			img = Image.open(io.BytesIO(img_bytes))
			page_text = pytesseract.image_to_string(img)
			if page_text:
				texts.append(page_text.strip())
		except Exception:
			continue

	return "\n\n".join(texts).strip()