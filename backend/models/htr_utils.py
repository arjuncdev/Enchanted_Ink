"""
htr_utils.py  -  shared helpers for Enchanted Ink (training, eval, laptop inference).

IMPORTANT: use prep_line_image() for BOTH the training images and live app images,
so the model always sees the same style: white background, dark ink,
tight crop (16 px margin), ink height 120 px.
"""
import numpy as np
import torch
from PIL import Image, ImageFilter

INK_H = 120      # ink height in px after prep
MARGIN = 16      # white margin around the line


def prep_line_image(img, ink_h=INK_H, margin=MARGIN):
    """Stylus screenshot / line photo -> white bg, dark solid ink, tight crop."""
    rgb = np.asarray(img.convert("RGB")).astype(np.float32)
    bg = np.median(rgb.reshape(-1, 3), axis=0)              # background colour
    diff = np.abs(rgb - bg).max(axis=2)                      # distance from background
    strength = np.clip((diff - 55) / 100.0, 0, 1)            # 0 = bg / grid dots, 1 = ink
    mask = strength > 0.3
    if mask.sum() < 20:                                      # nothing found -> return as is
        return img.convert("RGB")
    ys, xs = np.nonzero(mask)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    s = strength[y0:y1, x0:x1]
    h, w = s.shape
    scale = ink_h / h
    s_img = Image.fromarray((s * 255).astype(np.uint8)).resize(
        (max(1, int(w * scale)), ink_h), Image.LANCZOS)
    arr = 255 - np.asarray(s_img).astype(np.float32) * (238 / 255.0)   # 255 white .. 17 ink
    out = Image.fromarray(arr.astype(np.uint8)).filter(ImageFilter.MinFilter(3))  # bolder strokes
    canvas = Image.new("L", (out.width + 2 * margin, ink_h + 2 * margin), 255)
    canvas.paste(out, (margin, margin))
    return canvas.convert("RGB")


def load_model(path, device="cpu"):
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel
    processor = TrOCRProcessor.from_pretrained(path)
    model = VisionEncoderDecoderModel.from_pretrained(path).to(device).eval()
    return model, processor


@torch.inference_mode()
def recognize(model, processor, images, device="cpu", beams=4, max_new_tokens=64):
    """images: list of PIL images (already prepped). Returns (texts, confidences 0..1).
    Confidence = exp(mean token log-prob) of the best beam (uncalibrated)."""
    pv = processor(images=[im.convert("RGB") for im in images],
                   return_tensors="pt").pixel_values.to(device)
    out = model.generate(
        pv,
        num_beams=beams,
        length_penalty=1.0,          # so sequences_scores = mean log-prob
        no_repeat_ngram_size=3,      # stops "Of Of Of Of" / "presentationation"
        early_stopping=True,
        max_new_tokens=max_new_tokens,
        return_dict_in_generate=True,
        output_scores=True,
    )
    texts = [t.strip() for t in processor.batch_decode(out.sequences, skip_special_tokens=True)]
    scores = getattr(out, "sequences_scores", None)
    if scores is None:
        confs = [float("nan")] * len(texts)
    else:
        confs = torch.exp(scores).tolist()
    return texts, confs
