# University GPU runbook (Phase R1 + R2 baseline)

This runbook takes you from an empty university machine to baseline results on your laptop at home.
- **No Claude Code is needed at the university.** Every step is a script that is already in the repository.
- **The scripts work on Windows and Linux.** Each step shows both versions.
- **The dataset can come either way:** the Kaggle zip (`archive.zip`, 3.15 GB), or the folder extracted from it. Every command below accepts both.
- **Never store a password, token or key on the university machine.**
  - The GitHub repository is public, so cloning needs no login.
  - The dataset arrives on a USB stick.
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

1. **If you bring the zip, check that it finished downloading.**
   - No `.crdownload` or `.partial` file is left.
   - The zip opens and lists its files without errors.
   - Optional: list it in Python without unpacking it: `python -c "import zipfile,sys; z=zipfile.ZipFile(sys.argv[1]); print(len(z.namelist()), 'entries'); print(z.testzip() or 'CRC OK')" <zip>`
2. **Record its checksum.** You will compare it after copying.
   - Windows: `Get-FileHash -Algorithm SHA256 <zip>`
   - Linux: `sha256sum <zip>`
3. **Copy the zip, or the extracted `kaggle_kebede` folder, to a USB stick.** Use exFAT or NTFS: FAT32 cannot hold files over 4 GB.
   - **If you copy the folder**, record its file count and total size for comparison:
     - Windows: `Get-ChildItem -Recurse -File <folder> | Measure-Object -Property Length -Sum`
     - Linux: `find <folder> -type f | wc -l; du -sb <folder>`
     - Expect Count = 5192.
4. **If the university machine has no `git`,** also download the repository as a ZIP from GitHub (Code → Download ZIP) onto the USB stick.

## 1. Get the code and the zip onto the university machine

Work in a folder you own, so nothing needs admin rights. Examples: `C:\Users\<you>\oscc` or `D:\oscc` on Windows, `~/oscc` on Linux.

**With git (preferred):** this is an HTTPS clone of a public repository, so it needs no credentials.

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

**Without git:** unzip the repository ZIP from the USB stick into the same place. The folder will be called `FYP-Fall-2026-main`; use it in place of `FYP-Fall-2026` below.

**Copy the dataset** into the gitignored raw-data folder, then check that it copied correctly. Use **either** the zip (first two blocks) **or** the extracted folder (last two blocks). The scripts only **read** `ml_research/data/raw/`; nothing there is ever moved, changed or deleted.

```powershell
# Windows
mkdir ml_research\data\raw\kaggle_kebede -Force
copy E:\<your zip>.zip ml_research\data\raw\kaggle_kebede\
Get-FileHash -Algorithm SHA256 ml_research\data\raw\kaggle_kebede\<your zip>.zip   # must match home
```

```bash
# Linux
mkdir -p ml_research/data/raw/kaggle_kebede
cp /media/<you>/<usb>/<your zip>.zip ml_research/data/raw/kaggle_kebede/
sha256sum ml_research/data/raw/kaggle_kebede/<your zip>.zip                       # must match home
```

**Or the extracted folder.** `kaggle_kebede` holds `train/`, `val/` and `test/` directly.

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

In the commands below, `<dataset>` is **either** `ml_research/data/raw/kaggle_kebede` (the folder) **or** `ml_research/data/raw/kaggle_kebede/<your zip>.zip`.

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

`uni_run` runs `prepare → sweep → train-all → evaluate → report → pack-results` in the background. It takes **the extracted folder or the zip** (`<dataset>` from section 1). The examples use the folder.

> **Decision needed before the run: the tissue threshold.**
> - On the 60-image sample of the real data, the agreed O5 filter (plain Otsu on saturation) kept only 31% of grid tiles. 11 of the 60 images fell back to a single tile.
> - With the threshold capped at 40, it kept 82% of tiles, with no fallbacks.
> - If the team adopts the cap, add `-MaxTissueThreshold 40` (Windows) or `--max-tissue-threshold 40` (Linux) to the command below.
> - Use the same value for every run; it is recorded in `dataset.json`.

```powershell
# Windows: opens a separate minimized window
powershell -ExecutionPolicy Bypass -File ml_research\scripts\uni_run.ps1 -Raw ml_research\data\raw\kaggle_kebede
Get-Content -Wait ml_research\runs\uni_run.log      # watch progress (Ctrl+C stops watching, not the run)
```

```bash
# Linux: uses tmux if installed, otherwise nohup (survives logging out)
bash ml_research/scripts/uni_run.sh ml_research/data/raw/kaggle_kebede
tail -f ml_research/runs/uni_run.log               # watch progress (Ctrl+C stops watching, not the run)
```

**What happens in each step:**
- **prepare:**
  - Reads the zip or folder one image at a time and computes SHA-256 and pHash.
  - Excludes the publisher's `aug_*` copies by name.
  - Removes duplicate and near-duplicate originals (pHash, SHA-256).
  - Makes a grouped, stratified 70:15:15 split with seed 42 and runs the leakage test.
  - Writes 224×224 patches with the O5 rule.
  - Prints a count table per class, split and magnification. Keep it for the dataset audit.
- **sweep:** short runs of all four models for each learning rate in `protocol.yaml`; writes `runs/sweep/chosen_lr.json`.
- **train-all:** trains the four models with seed 42 and the chosen learning rate. The log shows seconds per epoch and an ETA.
- **evaluate:** test metrics with 95% bootstrap CIs, plus parameters, GFLOPs, CPU and GPU latency.
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
