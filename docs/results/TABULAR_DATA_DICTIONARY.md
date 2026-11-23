# Tabular data dictionary (`TABULAR_FEATURES_VERSION` tf-1.0.0)

Phase T, proposed FR-7.11. Two tables are produced by `oscc-ml tabular-extract` from the kept images
of the prepared manifest, on the **existing** split (no new split):

- `ml_research/data/processed/tabular/oscc_features_v1.csv`: identifiers, metadata and the
  **pathology features** used by the tabular models (gitignored; its SHA-256 is recorded in
  `extraction.json` and in the "Release" section below);
- `ml_research/data/processed/tabular/oscc_shortcut_cues_v1.csv`: **non-pathology cues**, used ONLY
  by the shortcut check, never by the models.

## How every feature is measured

1. The image is read once; its SHA-256 must equal the manifest's, and its size the manifest's.
2. **Downsized copy:** `PIL.Image.reduce(4)`, a 4x4 box average. 2048x1536 becomes 512x384,
   1536x2048 becomes 384x512, and the one 1435x916 image becomes 358x229. One downsized pixel
   covers 4x4 original pixels.
3. **Tissue mask:** the training rule of ADR-0002 on the downsized copy: HSV saturation
   (`oscc_ml.preprocess.saturation`) > min(Otsu threshold, 40). If fewer than 500 pixels pass, all
   pixels are used and `tissue_mask_fallback` = 1.
4. Every feature below is computed over the tissue pixels only (GLCM: pairs with both pixels in
   tissue; LBP: interior tissue pixels), except the whole-frame colour histogram in the cue table.
5. Floats are written with 10 significant digits; rows are sorted by `image_id`. Two extractions are
   byte-identical (tested).

Magnification and image size are **metadata**, not features. The models do not see them; the
"+ magnification" ablation adds one column `is_400x` (1 for 400x) at training time.

Known limitation of the stain features: the Ruifrok-Johnston stain vectors are generic; on these
images (bluish-purple, high `rgb_b_mean`) eosin concentrations are small and can be slightly
negative. The values are used as relative measurements, not absolute stain amounts.

## `oscc_features_v1.csv`

| Column | Meaning | Unit | Computation | Code |
| --- | --- | --- | --- | --- |
| `image_id` | Image identifier from the manifest | text | copied from `manifest.csv` | `ml_research/src/oscc_ml/tabular/extract.py` |
| `split` | train / val / test (the EXISTING grouped split) | text | copied from `manifest.csv` | `ml_research/src/oscc_ml/tabular/extract.py` |
| `label` | 0 = non-OSCC (Normal), 1 = OSCC | 0/1 | copied from `manifest.csv` | `ml_research/src/oscc_ml/tabular/extract.py` |
| `magnification` | 100x or 400x (metadata; used only in the ablation) | text | copied from `manifest.csv` | `ml_research/src/oscc_ml/tabular/extract.py` |
| `group_id` | pHash similarity group (split and bootstrap unit) | text | copied from `manifest.csv` | `ml_research/src/oscc_ml/tabular/extract.py` |
| `width` | Original image width (metadata, not a feature) | px | copied from `manifest.csv`, checked against the decoded image | `ml_research/src/oscc_ml/tabular/extract.py` |
| `height` | Original image height (metadata, not a feature) | px | as `width` | `ml_research/src/oscc_ml/tabular/extract.py` |
| `original_path` | Path inside the raw release | text | copied from `manifest.csv` | `ml_research/src/oscc_ml/tabular/extract.py` |
| `tissue_fraction` | Share of downsized pixels that are tissue | 0-1 | mean of the ADR-0002 mask (saturation > min(Otsu, 40)) on the downsized copy | `features.tissue_mask` |
| `tissue_threshold` | Saturation threshold used (diagnostic, not a model input) | 0-255 | min(Otsu threshold of saturation, 40) | `features.tissue_mask` |
| `tissue_mask_fallback` | 1 if < 500 tissue pixels, so all pixels were used (diagnostic, not a model input) | 0/1 |  | `features.tissue_mask` |
| `rgb_r_mean` | Mean red value of tissue pixels | 0-255 | mean over tissue pixels | `features.colour_features` |
| `rgb_r_std` | SD of red over tissue pixels | 0-255 | population SD | `features.colour_features` |
| `rgb_g_mean` | Mean green value of tissue pixels | 0-255 | mean over tissue pixels | `features.colour_features` |
| `rgb_g_std` | SD of green over tissue pixels | 0-255 | population SD | `features.colour_features` |
| `rgb_b_mean` | Mean blue value of tissue pixels | 0-255 | mean over tissue pixels | `features.colour_features` |
| `rgb_b_std` | SD of blue over tissue pixels | 0-255 | population SD | `features.colour_features` |
| `hsv_h_circular_mean_deg` | Mean hue (circular) | degrees 0-360 | Pillow HSV hue (0-255 -> angle), atan2 of mean sin/cos | `features.colour_features` |
| `hsv_h_resultant_length` | Hue concentration (1 = one hue) | 0-1 | length of the mean unit hue vector | `features.colour_features` |
| `hsv_s_mean` | Mean HSV saturation | 0-255 | Pillow `convert('HSV')`, mean over tissue | `features.colour_features` |
| `hsv_s_std` | SD of HSV saturation | 0-255 | population SD | `features.colour_features` |
| `hsv_v_mean` | Mean HSV value (brightness) | 0-255 | Pillow `convert('HSV')`, mean over tissue | `features.colour_features` |
| `hsv_v_std` | SD of HSV value (brightness) | 0-255 | population SD | `features.colour_features` |
| `lab_l_mean` | Mean CIE lightness L* | 0-100 | sRGB -> linear -> XYZ (D65) -> L*a*b* | `features.srgb_to_lab` |
| `lab_l_std` | SD of CIE lightness L* | 0-100 | population SD | `features.srgb_to_lab` |
| `lab_a_mean` | Mean CIE a* (green-red) | about -128..127 | sRGB -> linear -> XYZ (D65) -> L*a*b* | `features.srgb_to_lab` |
| `lab_a_std` | SD of CIE a* (green-red) | about -128..127 | population SD | `features.srgb_to_lab` |
| `lab_b_mean` | Mean CIE b* (blue-yellow) | about -128..127 | sRGB -> linear -> XYZ (D65) -> L*a*b* | `features.srgb_to_lab` |
| `lab_b_std` | SD of CIE b* (blue-yellow) | about -128..127 | population SD | `features.srgb_to_lab` |
| `he_h_od_mean` | Mean hematoxylin (nuclear, blue-purple) concentration | optical density | OD = -log10((I+1)/256); concentrations = OD x inverse of the Ruifrok-Johnston stain matrix (rows normalised) | `features.stain_concentrations` |
| `he_h_od_std` | Sd hematoxylin (nuclear, blue-purple) concentration | optical density | OD = -log10((I+1)/256); concentrations = OD x inverse of the Ruifrok-Johnston stain matrix (rows normalised) | `features.stain_concentrations` |
| `he_h_od_p10` | 10th percentile hematoxylin (nuclear, blue-purple) concentration | optical density | OD = -log10((I+1)/256); concentrations = OD x inverse of the Ruifrok-Johnston stain matrix (rows normalised) | `features.stain_concentrations` |
| `he_h_od_p50` | Median hematoxylin (nuclear, blue-purple) concentration | optical density | OD = -log10((I+1)/256); concentrations = OD x inverse of the Ruifrok-Johnston stain matrix (rows normalised) | `features.stain_concentrations` |
| `he_h_od_p90` | 90th percentile hematoxylin (nuclear, blue-purple) concentration | optical density | OD = -log10((I+1)/256); concentrations = OD x inverse of the Ruifrok-Johnston stain matrix (rows normalised) | `features.stain_concentrations` |
| `he_e_od_mean` | Mean eosin (cytoplasm/stroma, pink) concentration | optical density | OD = -log10((I+1)/256); concentrations = OD x inverse of the Ruifrok-Johnston stain matrix (rows normalised) | `features.stain_concentrations` |
| `he_e_od_std` | Sd eosin (cytoplasm/stroma, pink) concentration | optical density | OD = -log10((I+1)/256); concentrations = OD x inverse of the Ruifrok-Johnston stain matrix (rows normalised) | `features.stain_concentrations` |
| `he_e_od_p10` | 10th percentile eosin (cytoplasm/stroma, pink) concentration | optical density | OD = -log10((I+1)/256); concentrations = OD x inverse of the Ruifrok-Johnston stain matrix (rows normalised) | `features.stain_concentrations` |
| `he_e_od_p50` | Median eosin (cytoplasm/stroma, pink) concentration | optical density | OD = -log10((I+1)/256); concentrations = OD x inverse of the Ruifrok-Johnston stain matrix (rows normalised) | `features.stain_concentrations` |
| `he_e_od_p90` | 90th percentile eosin (cytoplasm/stroma, pink) concentration | optical density | OD = -log10((I+1)/256); concentrations = OD x inverse of the Ruifrok-Johnston stain matrix (rows normalised) | `features.stain_concentrations` |
| `he_h_share` | Hematoxylin share of stain | 0-1 | mean(max(H,0)) / (mean(max(H,0)) + mean(max(E,0))) | `features.stain_features` |
| `od_total_mean` | Mean summed optical density (overall stain darkness) | optical density | mean over tissue of OD_R + OD_G + OD_B | `features.stain_features` |
| `glcm_contrast_d1` | GLCM contrast at distance 1 (downsized px = 4 original px) | unitless | sum P(i,j)(i-j)^2: local intensity variation; grey = Pillow 'L' quantised to 32 levels; symmetric, normalised; pairs with both pixels in tissue; mean of 0/45/90/135 degrees | `features.texture_features` |
| `glcm_dissimilarity_d1` | GLCM dissimilarity at distance 1 (downsized px = 4 original px) | unitless | sum P(i,j)|i-j|; grey = Pillow 'L' quantised to 32 levels; symmetric, normalised; pairs with both pixels in tissue; mean of 0/45/90/135 degrees | `features.texture_features` |
| `glcm_homogeneity_d1` | GLCM homogeneity at distance 1 (downsized px = 4 original px) | unitless | sum P(i,j)/(1+(i-j)^2): closeness to the diagonal; grey = Pillow 'L' quantised to 32 levels; symmetric, normalised; pairs with both pixels in tissue; mean of 0/45/90/135 degrees | `features.texture_features` |
| `glcm_asm_d1` | GLCM asm at distance 1 (downsized px = 4 original px) | unitless | angular second moment, sum P(i,j)^2: uniformity; grey = Pillow 'L' quantised to 32 levels; symmetric, normalised; pairs with both pixels in tissue; mean of 0/45/90/135 degrees | `features.texture_features` |
| `glcm_energy_d1` | GLCM energy at distance 1 (downsized px = 4 original px) | unitless | sqrt(ASM); grey = Pillow 'L' quantised to 32 levels; symmetric, normalised; pairs with both pixels in tissue; mean of 0/45/90/135 degrees | `features.texture_features` |
| `glcm_correlation_d1` | GLCM correlation at distance 1 (downsized px = 4 original px) | unitless | linear dependency of neighbouring grey levels; grey = Pillow 'L' quantised to 32 levels; symmetric, normalised; pairs with both pixels in tissue; mean of 0/45/90/135 degrees | `features.texture_features` |
| `glcm_contrast_d2` | GLCM contrast at distance 2 (downsized px = 8 original px) | unitless | sum P(i,j)(i-j)^2: local intensity variation; grey = Pillow 'L' quantised to 32 levels; symmetric, normalised; pairs with both pixels in tissue; mean of 0/45/90/135 degrees | `features.texture_features` |
| `glcm_dissimilarity_d2` | GLCM dissimilarity at distance 2 (downsized px = 8 original px) | unitless | sum P(i,j)|i-j|; grey = Pillow 'L' quantised to 32 levels; symmetric, normalised; pairs with both pixels in tissue; mean of 0/45/90/135 degrees | `features.texture_features` |
| `glcm_homogeneity_d2` | GLCM homogeneity at distance 2 (downsized px = 8 original px) | unitless | sum P(i,j)/(1+(i-j)^2): closeness to the diagonal; grey = Pillow 'L' quantised to 32 levels; symmetric, normalised; pairs with both pixels in tissue; mean of 0/45/90/135 degrees | `features.texture_features` |
| `glcm_asm_d2` | GLCM asm at distance 2 (downsized px = 8 original px) | unitless | angular second moment, sum P(i,j)^2: uniformity; grey = Pillow 'L' quantised to 32 levels; symmetric, normalised; pairs with both pixels in tissue; mean of 0/45/90/135 degrees | `features.texture_features` |
| `glcm_energy_d2` | GLCM energy at distance 2 (downsized px = 8 original px) | unitless | sqrt(ASM); grey = Pillow 'L' quantised to 32 levels; symmetric, normalised; pairs with both pixels in tissue; mean of 0/45/90/135 degrees | `features.texture_features` |
| `glcm_correlation_d2` | GLCM correlation at distance 2 (downsized px = 8 original px) | unitless | linear dependency of neighbouring grey levels; grey = Pillow 'L' quantised to 32 levels; symmetric, normalised; pairs with both pixels in tissue; mean of 0/45/90/135 degrees | `features.texture_features` |
| `glcm_contrast_d4` | GLCM contrast at distance 4 (downsized px = 16 original px) | unitless | sum P(i,j)(i-j)^2: local intensity variation; grey = Pillow 'L' quantised to 32 levels; symmetric, normalised; pairs with both pixels in tissue; mean of 0/45/90/135 degrees | `features.texture_features` |
| `glcm_dissimilarity_d4` | GLCM dissimilarity at distance 4 (downsized px = 16 original px) | unitless | sum P(i,j)|i-j|; grey = Pillow 'L' quantised to 32 levels; symmetric, normalised; pairs with both pixels in tissue; mean of 0/45/90/135 degrees | `features.texture_features` |
| `glcm_homogeneity_d4` | GLCM homogeneity at distance 4 (downsized px = 16 original px) | unitless | sum P(i,j)/(1+(i-j)^2): closeness to the diagonal; grey = Pillow 'L' quantised to 32 levels; symmetric, normalised; pairs with both pixels in tissue; mean of 0/45/90/135 degrees | `features.texture_features` |
| `glcm_asm_d4` | GLCM asm at distance 4 (downsized px = 16 original px) | unitless | angular second moment, sum P(i,j)^2: uniformity; grey = Pillow 'L' quantised to 32 levels; symmetric, normalised; pairs with both pixels in tissue; mean of 0/45/90/135 degrees | `features.texture_features` |
| `glcm_energy_d4` | GLCM energy at distance 4 (downsized px = 16 original px) | unitless | sqrt(ASM); grey = Pillow 'L' quantised to 32 levels; symmetric, normalised; pairs with both pixels in tissue; mean of 0/45/90/135 degrees | `features.texture_features` |
| `glcm_correlation_d4` | GLCM correlation at distance 4 (downsized px = 16 original px) | unitless | linear dependency of neighbouring grey levels; grey = Pillow 'L' quantised to 32 levels; symmetric, normalised; pairs with both pixels in tissue; mean of 0/45/90/135 degrees | `features.texture_features` |
| `lbp_riu2_bin0` | Share of tissue pixels with LBP code 0: uniform pattern with 0 neighbour(s) >= centre (edges, corners, spots) | 0-1 | uniform rotation-invariant LBP (riu2), 8 square neighbours, radius 1, on the grey image | `features.lbp_features` |
| `lbp_riu2_bin1` | Share of tissue pixels with LBP code 1: uniform pattern with 1 neighbour(s) >= centre (edges, corners, spots) | 0-1 | uniform rotation-invariant LBP (riu2), 8 square neighbours, radius 1, on the grey image | `features.lbp_features` |
| `lbp_riu2_bin2` | Share of tissue pixels with LBP code 2: uniform pattern with 2 neighbour(s) >= centre (edges, corners, spots) | 0-1 | uniform rotation-invariant LBP (riu2), 8 square neighbours, radius 1, on the grey image | `features.lbp_features` |
| `lbp_riu2_bin3` | Share of tissue pixels with LBP code 3: uniform pattern with 3 neighbour(s) >= centre (edges, corners, spots) | 0-1 | uniform rotation-invariant LBP (riu2), 8 square neighbours, radius 1, on the grey image | `features.lbp_features` |
| `lbp_riu2_bin4` | Share of tissue pixels with LBP code 4: uniform pattern with 4 neighbour(s) >= centre (edges, corners, spots) | 0-1 | uniform rotation-invariant LBP (riu2), 8 square neighbours, radius 1, on the grey image | `features.lbp_features` |
| `lbp_riu2_bin5` | Share of tissue pixels with LBP code 5: uniform pattern with 5 neighbour(s) >= centre (edges, corners, spots) | 0-1 | uniform rotation-invariant LBP (riu2), 8 square neighbours, radius 1, on the grey image | `features.lbp_features` |
| `lbp_riu2_bin6` | Share of tissue pixels with LBP code 6: uniform pattern with 6 neighbour(s) >= centre (edges, corners, spots) | 0-1 | uniform rotation-invariant LBP (riu2), 8 square neighbours, radius 1, on the grey image | `features.lbp_features` |
| `lbp_riu2_bin7` | Share of tissue pixels with LBP code 7: uniform pattern with 7 neighbour(s) >= centre (edges, corners, spots) | 0-1 | uniform rotation-invariant LBP (riu2), 8 square neighbours, radius 1, on the grey image | `features.lbp_features` |
| `lbp_riu2_bin8` | Share of tissue pixels with LBP code 8: flat area (all neighbours >= centre) | 0-1 | uniform rotation-invariant LBP (riu2), 8 square neighbours, radius 1, on the grey image | `features.lbp_features` |
| `lbp_riu2_bin9` | Share of tissue pixels with LBP code 9: non-uniform pattern (> 2 transitions) | 0-1 | uniform rotation-invariant LBP (riu2), 8 square neighbours, radius 1, on the grey image | `features.lbp_features` |
| `nuc_h_threshold_od` | Hematoxylin OD threshold for 'dark' pixels | optical density | Otsu on hematoxylin OD within tissue (256-bin histogram) | `features.nuclei_features` |
| `nuc_h_positive_fraction` | Share of tissue pixels above that threshold | 0-1 |  | `features.nuclei_features` |
| `nuc_blob_count` | Number of dark blobs (nuclei proxy) | count | 8-connected components of hematoxylin-positive tissue pixels with >= 2 px | `features.nuclei_features` |
| `nuc_blob_density_per_10k_tissue_px` | Dark blobs per 10,000 tissue pixels (nuclear density proxy) | per 10k downsized px | count / tissue pixels x 10,000 | `features.nuclei_features` |
| `nuc_blob_area_mean_px` | Mean blob area (nuclear size proxy) | downsized px (1 px = 16 original px) | over blobs >= 2 px | `features.nuclei_features` |
| `nuc_blob_area_median_px` | Median blob area (nuclear size proxy) | downsized px (1 px = 16 original px) | over blobs >= 2 px | `features.nuclei_features` |
| `nuc_blob_area_std_px` | SD of blob area (nuclear size proxy) | downsized px (1 px = 16 original px) | over blobs >= 2 px | `features.nuclei_features` |
| `nuc_blob_area_p90_px` | 90th percentile of blob area (nuclear size proxy) | downsized px (1 px = 16 original px) | over blobs >= 2 px | `features.nuclei_features` |

## `oscc_shortcut_cues_v1.csv`

Columns `image_id`, `split`, `label`, `magnification`, `group_id` as above, then:

| Column | Meaning | Unit | Computation | Code |
| --- | --- | --- | --- | --- |
| `file_size_bytes` | Size of the JPEG file | bytes | length of the file bytes | `shortcut.file_cues` |
| `img_width_px` | Image width | px | decoded image | `shortcut.file_cues` |
| `img_height_px` | Image height | px | decoded image | `shortcut.file_cues` |
| `img_aspect_ratio` | Width / height | ratio |  | `shortcut.file_cues` |
| `bytes_per_pixel` | Compressed bytes per pixel (compression level proxy) | bytes/px | file size / (width x height) | `shortcut.file_cues` |
| `jpeg_progressive` | Progressive JPEG flag | 0/1 | Pillow `info` | `shortcut.file_cues` |
| `jpeg_subsampling` | Chroma subsampling code (-1 unknown) | code | Pillow `JpegImagePlugin.get_sampling` | `shortcut.file_cues` |
| `has_exif` | EXIF block present | 0/1 | Pillow `info['exif']` | `shortcut.file_cues` |
| `has_icc_profile` | ICC profile present | 0/1 | Pillow `info['icc_profile']` | `shortcut.file_cues` |
| `dpi_x` | Stored horizontal DPI (0 if none) | dpi | Pillow `info['dpi']` | `shortcut.file_cues` |
| `is_rgb_mode` | Decoded mode is RGB | 0/1 |  | `shortcut.file_cues` |
| `jpeg_n_quant_tables` | Number of JPEG quantisation tables | count | Pillow `quantization` | `shortcut._quant_table_stats` |
| `jpeg_qtable_luma_mean` | Mean luminance quantisation step (JPEG quality proxy; -1 if none) | step |  | `shortcut._quant_table_stats` |
| `jpeg_qtable_chroma_mean` | Mean chrominance quantisation step (-1 if none) | step |  | `shortcut._quant_table_stats` |
| `ghist_r_bin0` | Share of ALL downsized pixels (tissue and background) with R in [0, 31] | 0-1 | 8-bin histogram of the whole frame | `shortcut.global_colour_histogram` |
| `ghist_r_bin1` | Share of ALL downsized pixels (tissue and background) with R in [32, 63] | 0-1 | 8-bin histogram of the whole frame | `shortcut.global_colour_histogram` |
| `ghist_r_bin2` | Share of ALL downsized pixels (tissue and background) with R in [64, 95] | 0-1 | 8-bin histogram of the whole frame | `shortcut.global_colour_histogram` |
| `ghist_r_bin3` | Share of ALL downsized pixels (tissue and background) with R in [96, 127] | 0-1 | 8-bin histogram of the whole frame | `shortcut.global_colour_histogram` |
| `ghist_r_bin4` | Share of ALL downsized pixels (tissue and background) with R in [128, 159] | 0-1 | 8-bin histogram of the whole frame | `shortcut.global_colour_histogram` |
| `ghist_r_bin5` | Share of ALL downsized pixels (tissue and background) with R in [160, 191] | 0-1 | 8-bin histogram of the whole frame | `shortcut.global_colour_histogram` |
| `ghist_r_bin6` | Share of ALL downsized pixels (tissue and background) with R in [192, 223] | 0-1 | 8-bin histogram of the whole frame | `shortcut.global_colour_histogram` |
| `ghist_r_bin7` | Share of ALL downsized pixels (tissue and background) with R in [224, 255] | 0-1 | 8-bin histogram of the whole frame | `shortcut.global_colour_histogram` |
| `ghist_g_bin0` | Share of ALL downsized pixels (tissue and background) with G in [0, 31] | 0-1 | 8-bin histogram of the whole frame | `shortcut.global_colour_histogram` |
| `ghist_g_bin1` | Share of ALL downsized pixels (tissue and background) with G in [32, 63] | 0-1 | 8-bin histogram of the whole frame | `shortcut.global_colour_histogram` |
| `ghist_g_bin2` | Share of ALL downsized pixels (tissue and background) with G in [64, 95] | 0-1 | 8-bin histogram of the whole frame | `shortcut.global_colour_histogram` |
| `ghist_g_bin3` | Share of ALL downsized pixels (tissue and background) with G in [96, 127] | 0-1 | 8-bin histogram of the whole frame | `shortcut.global_colour_histogram` |
| `ghist_g_bin4` | Share of ALL downsized pixels (tissue and background) with G in [128, 159] | 0-1 | 8-bin histogram of the whole frame | `shortcut.global_colour_histogram` |
| `ghist_g_bin5` | Share of ALL downsized pixels (tissue and background) with G in [160, 191] | 0-1 | 8-bin histogram of the whole frame | `shortcut.global_colour_histogram` |
| `ghist_g_bin6` | Share of ALL downsized pixels (tissue and background) with G in [192, 223] | 0-1 | 8-bin histogram of the whole frame | `shortcut.global_colour_histogram` |
| `ghist_g_bin7` | Share of ALL downsized pixels (tissue and background) with G in [224, 255] | 0-1 | 8-bin histogram of the whole frame | `shortcut.global_colour_histogram` |
| `ghist_b_bin0` | Share of ALL downsized pixels (tissue and background) with B in [0, 31] | 0-1 | 8-bin histogram of the whole frame | `shortcut.global_colour_histogram` |
| `ghist_b_bin1` | Share of ALL downsized pixels (tissue and background) with B in [32, 63] | 0-1 | 8-bin histogram of the whole frame | `shortcut.global_colour_histogram` |
| `ghist_b_bin2` | Share of ALL downsized pixels (tissue and background) with B in [64, 95] | 0-1 | 8-bin histogram of the whole frame | `shortcut.global_colour_histogram` |
| `ghist_b_bin3` | Share of ALL downsized pixels (tissue and background) with B in [96, 127] | 0-1 | 8-bin histogram of the whole frame | `shortcut.global_colour_histogram` |
| `ghist_b_bin4` | Share of ALL downsized pixels (tissue and background) with B in [128, 159] | 0-1 | 8-bin histogram of the whole frame | `shortcut.global_colour_histogram` |
| `ghist_b_bin5` | Share of ALL downsized pixels (tissue and background) with B in [160, 191] | 0-1 | 8-bin histogram of the whole frame | `shortcut.global_colour_histogram` |
| `ghist_b_bin6` | Share of ALL downsized pixels (tissue and background) with B in [192, 223] | 0-1 | 8-bin histogram of the whole frame | `shortcut.global_colour_histogram` |
| `ghist_b_bin7` | Share of ALL downsized pixels (tissue and background) with B in [224, 255] | 0-1 | 8-bin histogram of the whole frame | `shortcut.global_colour_histogram` |

## Release

Filled from `extraction.json` of the committed extraction (see `docs/adr/0006-tabular-dataset-and-classifiers.md`).
