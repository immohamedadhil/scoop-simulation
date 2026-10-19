# SCOOP-Sim: Payment-Channel Congestion Research Prototype

SCOOP-Sim is a Python simulation for studying liquidity-based congestion in payment-channel networks, inspired by the paper [*SCOOP: CoSt-effective COngestiOn Attacks in Payment Channel Networks*](https://arxiv.org/abs/2503.12625).

It compares several attacker allocation strategies on synthetic graphs or a historical Lightning Network topology. For topology-based experiments, the graph structure and public channel metadata come from a snapshot, while directional balances are **modeled** because the snapshot does not reveal real channel balances.

> **Research status:** this is a research prototype and an independent SCOOP-inspired implementation. It is not the authors' official code, is not an exact reproduction of the paper, and does not connect to or attack a live Lightning Network node.

## What it explores

- **Random:** randomly allocates a sender's budget among candidate routes.
- **Greedy General:** prioritizes routes with larger current bottlenecks.
- **SPCR-Max:** allocates payments using a linear program based on path length and original path bottleneck, then applies feasible payments sequentially.
- **Joint SPCR-Max:** adds shared directed-channel balance constraints within the optimization for each budget owner. This is an extension in this simulator, using a standard optimization idea; it should not be described as a new optimization technique by itself.
- **No-attack baseline:** evaluates the same honest-payment workload without attacker locks.

The runner reports attacker-side congestion measures and network-impact measurements. The main congestion measures include locked payment, PCR, and SPCR with two `L_max` interpretations (`20` and `8`). It also records honest-payment success rate, success volume, and average routing attempts. See [the experiment design notes](docs/experimental-design.md) for modeling choices and limitations.

## Quick start

Recommended: Python 3.11 or 3.12.

### 1. Get the code

```bash
git clone https://github.com/YOUR_USERNAME/scoop-sim.git
cd scoop-sim
```

Replace `YOUR_USERNAME` with your GitHub username after you create the repository.

### 2. Create an environment and install dependencies

**Linux/macOS/AWS Ubuntu:**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

**Windows PowerShell:**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### 3. Run the tests

```bash
python -m pytest -q
```

### 4. Run a small synthetic smoke test

```bash
python -m scoop.experiments --quick --nodes 50 --k-paths 5 --output results_smoke
```

This is intended to verify that the pipeline runs, not to support research conclusions. Outputs are written to `results_smoke/`.

## Using the historical topology

The topology data is **not included** in this repository. Obtain the snapshot separately from the [TU Berlin discharged-PC data repository](https://git.tu-berlin.de/rohrer/discharged-pc-data). This project has been tested with `lngraph_2021_11_27__00_00.json.zst`.

Create a `data/` directory and download the snapshot (or follow the repository's current instructions if its hosting path changes):

```bash
mkdir -p data
wget -O data/lngraph_2021_11_27__00_00.json.zst \
  "https://git.tu-berlin.de/rohrer/discharged-pc-data/-/raw/master/snapshots/lngraph_2021_11_27__00_00.json.zst"
```

Since some Zstandard frames do not contain the decompressed size, stream-decompress the file rather than relying on a single-call `decompress()` operation:

```bash
mkdir -p data
python scripts/decompress_snapshot.py \
  data/lngraph_2021_11_27__00_00.json.zst \
  data/lngraph_2021_11_27__00_00.json
```

Then run a small historical-topology smoke test:

```bash
python -m scoop.experiments \
  --snapshot data/lngraph_2021_11_27__00_00.json \
  --quick \
  --k-paths 50 \
  --max-path-length 8 \
  --route-mode sender_to_all_receivers \
  --output results_real_smoke
```

Keep downloaded topology data and generated output out of Git. The provided `.gitignore` excludes common local data/output paths.

## Reproducible experiments

Example medium run:

```bash
python -m scoop.experiments \
  --snapshot data/lngraph_2021_11_27__00_00.json \
  --seeds 3 \
  --payments 500 \
  --budgets 75000000 100000000 \
  --amounts 10000 100000 1000000 \
  --k-paths 50 \
  --max-path-length 8 \
  --route-mode sender_to_all_receivers \
  --output results_real_medium
```

The full experiment is much more expensive. For long AWS runs, use `tmux`, log output, and checkpoint/resume support. See [Safe long-running experiments](docs/safe-runs.md) before starting one.

### Route and budget modes

- `sender_to_all_receivers` (default): each sender has routes to all designated receivers; routes originating at that sender share one budget.
- `fixed_pairs`: each sender routes only to its matching receiver.

These are separate modeling assumptions. Do not combine their outputs as though they were identical experiments. The paper leaves some details of attacker-pair construction and route enumeration unspecified, so these settings are explicit choices made by this implementation rather than proof of exact reproduction.

## Outputs

The chosen output directory includes:

- `experiment_config.json` — settings needed to identify the run
- `raw_results.csv` — per-scenario/per-strategy results
- `summary.csv` — group means and uncertainty intervals
- `paired_differences.csv` — attack-minus-baseline comparisons
- `summary_report.md` — compact report and caveats
- PNG charts — congestion and honest-payment metrics
- `raw_results_checkpoint.csv` — incremental checkpoint used for resume

## Important limitations

- The public topology snapshot does not provide actual directional channel balances. Balance splits are simulated and must be labelled **modeled, not observed**.
- This simulator uses a static graph. It does not model real payment fees, HTLC-slot exhaustion, lock expiries/timelocks, or live routing behavior in full protocol detail.
- Candidate routes are sampled across exact hop-length buckets under a bounded search budget. The resulting path-length distribution depends on the graph, attachment choice, and route-search parameters.
- The paper's exact topology, balance initialization, pair interpretation, and some metric details are not completely specified. Record assumptions and parameter values when reporting results.
- A high PCR/SPCR score does not automatically imply a large decrease in honest-payment success. Report the attacker-side metrics and the honest-workload impact separately.
- Small smoke runs are software checks, not evidence of attack effectiveness. Use multiple seeds and discuss uncertainty.

## Publish this project

For step-by-step instructions to test locally, initialize Git, create a GitHub repository, and push the code without uploading data or results, see [Publish this project to GitHub](docs/publishing-to-github.md).

## Project layout

```text
scoop-sim/
├── scoop/                 # simulation modules
│   ├── network.py         # directed balances and channel accounting
│   ├── generator.py       # synthetic network and balance models
│   ├── topology.py        # historical snapshot loading/preprocessing
│   ├── paths.py           # attacker endpoints and candidate route selection
│   ├── attacks.py         # attack allocation strategies
│   ├── metrics.py         # PCR/SPCR and summary metrics
│   ├── honest.py          # honest workload generation and routing
│   └── experiments.py     # CLI runner, outputs, plots, checkpoint/resume
├── tests/                 # automated tests
├── scripts/               # snapshot preparation tools
└── docs/                  # modeling and long-run notes
```

## Reference

Mohammed Ababneh, Kartick Kolachala, and Roopa Vishwanathan. “SCOOP: CoSt-effective COngestiOn Attacks in Payment Channel Networks.” arXiv:2503.12625 (2025). [Paper](https://arxiv.org/abs/2503.12625).

## License

The project includes an MIT license template. Before publishing, replace the placeholder copyright holder with your preferred copyright notice and confirm MIT is the license you want to use. See `LICENSE`.
