"""Tabular dataset and classical classifiers (Phase T; proposed FR-7.11, errata E16).

* ``features``: per-image colour, H&E stain, texture and nuclei-density features;
* ``shortcut``: non-pathology cues (file and JPEG properties, whole-frame colour) for the shortcut
  check only;
* ``extract``: streamed extraction of both tables from the kept images on the EXISTING split;
* ``models``: logistic regression, random forest and gradient boosting fitted on train only, tuned
  by grouped cross-validation, tau from validation, test used once; run folders in the image-run
  format.
"""

from __future__ import annotations

TABULAR_FEATURES_VERSION = "tf-1.0.0"
FEATURES_FILE = "oscc_features_v1.csv"
CUES_FILE = "oscc_shortcut_cues_v1.csv"
EXTRACTION_INFO_FILE = "extraction.json"
ID_COLUMNS = ("image_id", "split", "label", "magnification", "group_id")
METADATA_COLUMNS = ("width", "height", "original_path")
