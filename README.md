# SCOOP-Simulation: Payment-Channel Congestion Research Prototype

A Python research simulator for exploring congestion attacks in the Bitcoin Lightning Network. It compares attack strategies on synthetic networks and a historical Lightning topology, then measures their effects on ordinary payment success.

This is an independent, SCOOP-inspired research prototype,not the paper authors' official implementation or an exact reproduction. It does not interact with live Lightning nodes. Historical channel balances are not public in the snapshot, so balances in these experiments are **modeled, not observed**.

## What it compares

- **No attack** : baseline for legitimate payments.
- **Random** : chooses candidate routes at random.
- **Greedy General** : prioritizes routes using their current bottlenecks.
- **SPCR-Max** : uses linear programming to allocate amounts across candidate routes.
- **Joint SPCR-Max** : also constrains allocations that share a directed channel.

The simulator records locked payment value, PCR/SPCR congestion scores, and honest-payment success. See `scoop/` for the implementation and `results_real_full_diverse/` for the full experiment outputs.

## Results

The full historical-topology run completed **120 scenarios across 20 random seeds**, producing 600 strategy-level result rows. It tested five strategies, two per-sender budgets (75M and 100M satoshis), and three payment sizes (10,000, 100,000, and 1,000,000 satoshis). The processed topology contained **12,314 nodes and 57,790 channels**.

Joint SPCR-Max achieved higher mean SPCR-8 scores than SPCR-Max at both budgets:

| Budget per sender | SPCR-Max | Joint SPCR-Max |
|---:|---:|---:|
| 75M sats | 0.5659 | 0.5890 |
| 100M sats | 0.5701 | 0.5929 |

The effect on legitimate payment success was much smaller. Averaged across the two budgets and 20 seeds:

| Payment amount | No-attack success | Joint SPCR-Max success | Change |
|---:|---:|---:|---:|
| 10,000 sats | 87.250% | 87.144% | −0.106 percentage points |
| 100,000 sats | 32.353% | 32.206% | −0.148 percentage points |
| 1,000,000 sats | 6.195% | 6.125% | −0.071 percentage points |

These are results from this simulation setup, not measurements of the live network. The results suggest that higher attacker-side congestion scores do not necessarily mean a large drop in ordinary payment success.

Detailed data and plots are in [`results_real_full_diverse/`](results_real_full_diverse/), including `summary.csv`, `paired_differences.csv`, and `summary_report.md`.

## Run it

Python 3.11 or 3.12 is recommended.

```bash
git clone https://github.com/YOUR-USERNAME/scoop-simulation.git
cd scoop-simulation
python -m pip install -e ".[dev]"
python -m pytest -q
```

A small synthetic smoke test:

```bash
python -m scoop.experiments --quick --nodes 50 --k-paths 5 --output results_smoke
```

To run on the historical topology, download `lngraph_2021_11_27__00_00.json.zst` from the [TU Berlin discharged-PC data repository](https://git.tu-berlin.de/rohrer/discharged-pc-data), decompress it with `scripts/decompress_snapshot.py`, and pass the resulting JSON file with `--snapshot`. The dataset is not included in this repository.

## Limitations

Balances are modeled, not observed. The simulator uses a static graph and does not fully model real fees, HTLC-slot limits, timeouts, or live routing behavior. Results depend on the selected topology, routing settings, balance model, and assumptions. The current test suite checks software behavior; passing tests is not proof that the model represents every aspect of the live network.

## Reference

Mohammed Ababneh, Kartick Kolachala, and Roopa Vishwanathan, “SCOOP: CoSt-effective COngestiOn Attacks in Payment Channel Networks” (2025). [Paper](https://arxiv.org/abs/2503.12625).


## License

The project includes an MIT license template
