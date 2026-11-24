# University GPU runbook (Phase R1 + R2 baseline)

This runbook takes you from an empty university machine to baseline results on your laptop at home.
- **No Claude Code is needed at the university.** Every step is a script that is already in the repository.
- **The scripts work on Windows and Linux.** Each step shows both versions.
- **Code:** `git clone` over HTTPS from the public GitHub repository. This is the only route for the code, and it needs no login. The machine clones `main`.
- **Dataset (recommended route): Google Drive.** Download `oscc_kaggle_kebede_v1.zip` (3,191,603,059 bytes) from the Drive folder `FYP-OSCC-data` into `ml_research\data\raw\kaggle_kebede\`. The scripts read the zip directly and nothing is unpacked.
  - **SHA-256:** `f75d25682388c85469995e16c543ebe4f889cbe8d4c521df37e2bbd1be4a6c0d` (MD5 `2a1ae4331427793950e73d3414b82640`). Check the download against it before running anything (section 1).
  - The zip holds the Kaggle dataset unchanged and uncompressed (`kaggle_kebede/{train,val,test}/{Normal,OSCC}`, 5,192 files).
  - It was checked at home with `prepare --manifest-only`, giving the same manifest as the extracted folder (every row equal apart from the `kaggle_kebede/` path prefix). On 22 Nov 2026, with ADR-0005: 1,179 images kept, 35 label-conflict images excluded (ADR-0003), 2 reviewed pairs applied, split 829 / 174 / 176, leakage test passed. (On 21 Nov, at the old threshold of 6: 1,172 kept, 41 excluded.)
  - Other routes (section 1): the original Kaggle `archive.zip` on a USB stick, or the extracted folder.
- **Never store a password, token or key on the university machine.**
  - Sign in to Google only in a browser **private/incognito window**, only to download the zip, and sign out afterwards. Never let the browser save the password.
  - Do not sign in to Kaggle or GitHub there.

---

## 0. At home, before you go

**What the dataset looks like** (checked 18 Nov 2026 on the extracted folder; 5,192 files):

```
kaggle_kebede/
  train/Normal  231 originals + 2,204 aug_<n>_<n>.jpg     train/OSCC  747 originals + 1,764 aug_*
  val/Normal     28 originals                             val/OSCC     92 originals
  test/Normal    31 originals                             test/OSCC    95 originals
```

- Originals are named like `Normal_100x_12.jpg` / `OSCC_400x_7.jpg`, mostly 2048×1536 (some portrait 1536×2048, one 1435×916).
- There are 1,224 originals in total (290 Normal, 934 OSCC), matching the Rahman release.
- The `aug_*` files are the publisher's 224×224 augmented copies. Their names carry no magnification and no link to the original. `prepare` excludes them by name, and the manifest lists each one.

**Route A (Google Drive) needs nothing more at home.** `oscc_kaggle_kebede_v1.zip` was uploaded to the Drive folder `FYP-OSCC-data` on 22 Nov 2026. rclone confirmed that the Drive copy has the same size (3,191,603,059 bytes), MD5 and SHA-256 as the local zip. The SHA-256 is `f75d25682388c85469995e16c543ebe4f889cbe8d4c521df37e2bbd1be4a6c0d`; it is also in section 1, so you can read it on GitHub at the university. Steps 1–3 below are only for route B (USB).

1. **Check that `archive.zip` finished downloading.**
   - No `.crdownload` or `.partial` file is left.
   - The zip opens and lists its files without errors.
   - Optional: list it in Python without unpacking it: `python -c "import zipfile,sys; z=zipfile.ZipFile(sys.argv[1]); print(len(z.namelist()), 'entries'); print(z.testzip() or 'CRC OK')" <zip>`
2. **Record its checksum.** You will compare it after copying.
   - Windows: `Get-FileHash -Algorithm SHA256 <zip>`
   - Linux: `sha256sum <zip>`
3. **Copy `archive.zip` to a USB stick** formatted as exFAT or NTFS.
   - Fallback only: if you bring the extracted `kaggle_kebede` folder instead, record its file count and size for comparison. Expect Count = 5192.
     - Windows: `Get-ChildItem -Recurse -File <folder> | Measure-Object -Property Length -Sum`
     - Linux: `find <folder> -type f | wc -l; du -sb <folder>`
4. **Check that `main` on GitHub has everything you need.** The university machine clones `main`.

## 1. Get the code and the zip onto the university machine

Work in a folder you own, so nothing needs admin rights. Examples: `C:\Users\<you>\oscc` or `D:\oscc` on Windows, `~/oscc` on Linux.

**Code: `git clone` only.** It is an HTTPS clone of a public repository, so it needs no credentials. Check first with `git --version`. If git is missing, ask IT to install Git. Do not bring the code another way: every run records the git commit.

```powershell
# Windows PowerShell (NOT "Run as administrator")
mkdir $HOME\oscc; cd $HOME\oscc
git clone https://github.com/zaidbinnaveed/FYP-Fall-2026.git
cd FYP-Fall-2026
```

```bash
# Linux
mkdir -p ~/oscc && cd ~/oscc
git clone https://github.com/zaidbinnaveed/FYP-Fall-2026.git
cd FYP-Fall-2026
```

**Dataset route A (recommended): Google Drive.**

1. Open a **private/incognito** browser window, go to https://drive.google.com and sign in.
2. Open the folder `FYP-OSCC-data` and download `oscc_kaggle_kebede_v1.zip`, about 3.2 GB. Google warns that it cannot scan a file this large for viruses; choose **Download anyway**.
3. Move the file from Downloads into the raw-data folder and check it. **The SHA-256 must be exactly** `f75d25682388c85469995e16c543ebe4f889cbe8d4c521df37e2bbd1be4a6c0d`, and the size 3,191,603,059 bytes. If it differs, the download is incomplete or corrupt: delete it and download again.

   ```powershell
   # Windows
   mkdir ml_research\data\raw\kaggle_kebede -Force
   move $HOME\Downloads\oscc_kaggle_kebede_v1.zip ml_research\data\raw\kaggle_kebede\
   Get-FileHash -Algorithm SHA256 ml_research\data\raw\kaggle_kebede\oscc_kaggle_kebede_v1.zip
   (Get-Item ml_research\data\raw\kaggle_kebede\oscc_kaggle_kebede_v1.zip).Length
   ```

   ```bash
   # Linux
   mkdir -p ml_research/data/raw/kaggle_kebede
   mv ~/Downloads/oscc_kaggle_kebede_v1.zip ml_research/data/raw/kaggle_kebede/
   sha256sum ml_research/data/raw/kaggle_kebede/oscc_kaggle_kebede_v1.zip
   stat -c %s ml_research/data/raw/kaggle_kebede/oscc_kaggle_kebede_v1.zip
   ```

4. **Sign out of Google now**: account picture → Sign out. Then close the private window. Nothing else needs Google.

With route A, `<dataset>` below is `ml_research/data/raw/kaggle_kebede/oscc_kaggle_kebede_v1.zip`.

**Dataset route B: `archive.zip` on a USB stick.** Copy it into the gitignored raw-data folder, then check that it copied correctly. Replace `E:` with your USB drive letter. The scripts only **read** `ml_research/data/raw/`; nothing there is ever moved, changed or deleted.

```powershell
# Windows
mkdir ml_research\data\raw\kaggle_kebede -Force
copy E:\archive.zip ml_research\data\raw\kaggle_kebede\
Get-FileHash -Algorithm SHA256 ml_research\data\raw\kaggle_kebede\archive.zip   # must match the hash taken at home
```

```bash
# Linux
mkdir -p ml_research/data/raw/kaggle_kebede
cp /media/<you>/<usb>/archive.zip ml_research/data/raw/kaggle_kebede/
sha256sum ml_research/data/raw/kaggle_kebede/archive.zip                       # must match the hash taken at home
```

**Fallback: the extracted folder.** Use this only if you brought the folder instead of the zip. `kaggle_kebede` holds `train/`, `val/` and `test/` directly.

```powershell
# Windows (robocopy is built in; /E copies sub-folders)
robocopy E:\kaggle_kebede ml_research\data\raw\kaggle_kebede /E
Get-ChildItem -Recurse -File ml_research\data\raw\kaggle_kebede | Measure-Object -Property Length -Sum   # Count must be 5192
```

```bash
# Linux
mkdir -p ml_research/data/raw && cp -r /media/<you>/<usb>/kaggle_kebede ml_research/data/raw/
find ml_research/data/raw/kaggle_kebede -type f | wc -l          # must be 5192
```

In the commands below, `<dataset>` is:
- route A (Google Drive, recommended): `ml_research/data/raw/kaggle_kebede/oscc_kaggle_kebede_v1.zip`;
- route B (USB): `ml_research/data/raw/kaggle_kebede/archive.zip`;
- the folder fallback: `ml_research/data/raw/kaggle_kebede`.

Put only **one** of these in `kaggle_kebede\`.

## 2. One-time setup (no admin rights)

`uni_setup` does the following:
- installs `uv` for your user only, plus Python 3.11;
- creates `ml_research/.venv`;
- installs the locked dependencies, with the CUDA build of PyTorch chosen from `nvidia-smi`.

It downloads several GB from the internet. It is safe to run again.

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File ml_research\scripts\uni_setup.ps1
```

```bash
# Linux
bash ml_research/scripts/uni_setup.sh
```

The last line must read `SETUP COMPLETE`. Every failure prints `SETUP FAILED: <what> -- FIX: <how>`.

## 3. Readiness check (about 2–5 minutes)

`uni_check` checks the following, and finishes with a short GPU smoke run of all four models at batch size 32:
- the Python version;
- the GPU name and VRAM;
- free disk space (at least 40 GB);
- write access;
- the downloads of the pretrained weights.

The weights are cached in `ml_research/.cache/`.

```powershell
powershell -ExecutionPolicy Bypass -File ml_research\scripts\uni_check.ps1
```

```bash
bash ml_research/scripts/uni_check.sh
```

The last line must read `ALL CHECKS PASSED`. Each problem prints one line: `CHECK FAILED: <what> -- FIX: <how>`. The full output is saved to `ml_research/runs/uni_check.log`.

## 4. Optional dry run on synthetic data (a few minutes)

This proves the whole pipeline works on this machine before the real run. It uses separate folders, and its report step is *expected* to be refused, because the data is synthetic.

```powershell
# Windows
.\ml_research\.venv\Scripts\oscc-ml.exe make-test-zip --out ml_research\data\dryrun\test.zip --per-class 24 --augmented 1 --size 300x260
.\ml_research\.venv\Scripts\oscc-ml.exe uni-run --raw ml_research\data\dryrun\test.zip --data-root ml_research\data\dryrun\processed --runs-dir ml_research\data\dryrun\runs --dataset-version synthetic-dryrun --random-init --sweep-epochs 1 --epochs 1 --bootstrap 50 --latency-runs 5
Remove-Item -Recurse -Force ml_research\data\dryrun
```

```bash
# Linux
ml_research/.venv/bin/oscc-ml make-test-zip --out ml_research/data/dryrun/test.zip --per-class 24 --augmented 1 --size 300x260
ml_research/.venv/bin/oscc-ml uni-run --raw ml_research/data/dryrun/test.zip --data-root ml_research/data/dryrun/processed --runs-dir ml_research/data/dryrun/runs --dataset-version synthetic-dryrun --random-init --sweep-epochs 1 --epochs 1 --bootstrap 50 --latency-runs 5
rm -rf ml_research/data/dryrun
```

**Expected summary:**
- `prepare`, `sweep`, `train-all`, `evaluate` and `pack-results`: DONE.
- `report`: FAILED, with "synthetic dataset ... is never reported".

## 5. The real run

`uni_run` runs `prepare → sweep → train-all → evaluate → report → pack-results` in the background. It takes `<dataset>` from section 1; the examples use the Google Drive zip (route A). For route B, replace `oscc_kaggle_kebede_v1.zip` with `archive.zip`.

The tissue filter is the capped rule from ADR-0002 (`max_tissue_threshold: 40` in `protocol.yaml`). It is the default, so no extra option is needed.

```powershell
# Windows: opens a separate minimized window
powershell -ExecutionPolicy Bypass -File ml_research\scripts\uni_run.ps1 -Raw ml_research\data\raw\kaggle_kebede\oscc_kaggle_kebede_v1.zip
Get-Content -Wait ml_research\runs\uni_run.log      # watch progress (Ctrl+C stops watching, not the run)
```

```bash
# Linux: uses tmux if installed, otherwise nohup (survives logging out)
bash ml_research/scripts/uni_run.sh ml_research/data/raw/kaggle_kebede/oscc_kaggle_kebede_v1.zip
tail -f ml_research/runs/uni_run.log               # watch progress (Ctrl+C stops watching, not the run)
```

**What happens in each step:**
- **prepare:**
  - Reads the zip or folder one image at a time and computes SHA-256 and pHash.
  - Excludes the publisher's `aug_*` copies by name.
  - Removes duplicate and near-duplicate originals (SHA-256, pHash distance ≤ 4) and the 2 reviewed same-field pairs in `configs/data/reviewed_duplicates.yaml` (ADR-0005). The log line `reviewed duplicate list (ADR-0005): applied: 2 pair(s)` is expected; if a listed file is missing, `prepare` stops.
  - Excludes every duplicate cluster whose images carry both labels (ADR-0003). Expect 17 such clusters (14 byte-identical, 3 near-duplicate) and 35 excluded images; the log line `... carry both labels ...` is expected, and the run goes on.
  - Makes a grouped, stratified 70:15:15 split with seed 42 and runs the leakage test.
  - Writes 224×224 patches with the O5 rule and the ADR-0002 tissue cap.
  - Prints a count table per class, split and magnification. Keep it for the dataset audit.
- **sweep:** short runs of all four models for each learning rate in `protocol.yaml`; writes `runs/sweep/chosen_lr.json`.
- **train-all:** trains the four models with seed 42 and the chosen learning rate. The log shows seconds per epoch and an ETA.
- **evaluate:** the only step that reads the test split (audit M2). It predicts the test images from each run's `checkpoints/best.pt`, then computes tau from validation (and saves the validation curve), test metrics with 95% bootstrap CIs, per-magnification metrics, the confusion matrix with false-positive/false-negative image IDs, calibration (ECE), paired model comparisons (`runs/comparisons.json`), parameters, GFLOPs, CPU and GPU latency.
- **Observation record:** every sweep trial and training run writes `observations/epochs.jsonl` (per-epoch losses, validation AUC/recall/specificity/F1, LR, gradient norms, time, GPU memory, warnings) and `observations/training_summary.json` (best epoch, stop epoch and reason, resumes). `runs/decisions.jsonl` lists every decision with its reason (chosen and rejected LRs, kept checkpoint, tau, comparisons); `runs/environment.json` records the machine. All of this goes into `results_small.zip`.
- **Training journals:** after every sweep, training run and evaluation a plain-English `TRAINING_JOURNAL.md` is regenerated from those files only: one per run folder (what ran, the epoch table, the kept checkpoint and why training stopped, then tau and the test metrics with CIs), `runs/sweep/TRAINING_JOURNAL.md` (the chosen LR and why each other LR was rejected) and `runs/TRAINING_JOURNAL.md` (all steps and every decision with its reason). They are packed into `results_small.zip`; anything not yet run says "not yet run".
- **report:** writes `runs/report/baseline.md`, built from the run folders only.
- **pack-results:** writes `runs/export/results_small.zip` and `runs/export/checkpoints.zip`.

**While it runs:**
- **Windows:**
  - Do not close the minimized window.
  - Do not sign out; lock the screen with Win+L instead.
  - The script keeps Windows awake.
- **Linux:** you may log out.
- **If the machine restarts or the run stops, run the same `uni_run` command again.** Completed steps are skipped. Training continues from the last finished epoch.

**When it ends,** the log finishes with a summary listing every step as DONE, SKIPPED or FAILED, plus the total time.

## 6. Bring the results home

1. Copy these to the USB stick:
   - `ml_research/runs/export/results_small.zip`: configs, logs, metrics, predictions and the report. No checkpoints.
   - `ml_research/runs/export/checkpoints.zip`: the four best checkpoints, needed later for registration. About 0.5 GB for four FP32 models.
   - `ml_research/runs/uni_run.log`
2. **Leave no dataset copies behind on a shared machine.** After copying, delete `ml_research/data/` and `ml_research/runs/`, or the whole folder.
3. At home, in the repository:
   ```bash
   cd ml_research
   oscc-ml import-results /path/to/results_small.zip      # verifies SHA-256 of every file
   oscc-ml report --copy-to ../docs/results/baseline_fyp1.md
   ```
   Then commit `docs/results/baseline_fyp1.md` on a branch and open a PR. Never commit `runs/` or `data/`.

## 7. If something fails: send an error log

Send these files. They contain no passwords or keys:
- `ml_research/runs/uni_run.log`: full tracebacks.
- `ml_research/runs/uni_check.log`
- The output of `ml_research/.venv/Scripts/oscc-ml.exe env` (Windows) or `ml_research/.venv/bin/oscc-ml env` (Linux).

**Common problems:**

| Message | Fix |
| --- | --- |
| `SETUP FAILED: the NVIDIA driver supports CUDA X.Y, but torch ... is only built for cu132, cu134` | Ask IT to update the NVIDIA driver; this is the clean fix. As a last resort, rerun setup with an older PyTorch build, e.g. `uni_setup.ps1 -TorchVersion <v> -TorchvisionVersion <v> -CudaTag <tag>` (Linux: `--torch-version ... --torchvision-version ... --cuda-tag ...`). Every run records the versions actually used. |
| `CHECK FAILED: PyTorch cannot see a CUDA GPU` | Run `nvidia-smi`. If it fails, the driver is missing or broken: ask IT. |
| `CHECK FAILED: ... out of GPU memory at batch 32` | Close other GPU programs (see `nvidia-smi`). The protocol's batch size stays 32. |
| `CHECK FAILED: cannot download/load pretrained weights` | The machine needs internet access to download.pytorch.org and huggingface.co. Set `HTTPS_PROXY` if the university uses a proxy, or copy `ml_research/.cache/` from a machine that already has the weights. |
| `CHECK FAILED: only N GB free` | Free space, or clone onto a larger drive. |
| `prepare` fails with `name no class folder` | The dataset layout differs from what was expected (class folders must be named Normal or OSCC). Send the log; nothing is guessed. |
| `prepare` fails with `split proportions ...` | Similar images are being chained into very large groups. Rerun with a lower `--group-threshold` (via `oscc-ml prepare`) and send the log. |
| `another uni-run is already running` | One run is still active (check the other window, or `tmux ls`). Wait for it to finish. |
| PowerShell says scripts are disabled | Always start scripts with `powershell -ExecutionPolicy Bypass -File ...` as shown. This needs no admin rights. |
