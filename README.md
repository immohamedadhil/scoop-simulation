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

### Attack-related metrics

Means across 20 seeds. Locked payment is shown in millions of satoshis; balances are modeled. PCR and SPCR-8 are the simulator's route-set congestion scores.

| Budget per sender | Strategy | Locked payment (million sats) | Mean PCR | Mean SPCR-8 |
|---:|---|---:|---:|---:|
| 75M sats | Random | 103.07 | 0.5554 | 0.4226 |
| 75M sats | Greedy General | 331.34 | 0.4459 | 0.3251 |
| 75M sats | SPCR-Max | 341.14 | 0.7651 | 0.5659 |
| 75M sats | Joint SPCR-Max | 350.58 | 0.7841 | 0.5890 |
| 100M sats | Random | 121.10 | 0.5836 | 0.4427 |
| 100M sats | Greedy General | 380.13 | 0.4671 | 0.3397 |
| 100M sats | SPCR-Max | 403.79 | 0.7734 | 0.5701 |
| 100M sats | Joint SPCR-Max | 412.11 | 0.7920 | 0.5929 |

Joint SPCR-Max had the highest mean SPCR-8 score among the tested attack strategies at both budgets. These are simulated congestion metrics, not real funds or observed network behavior.

### Honest-payment success

Mean success rate across the two budgets and 20 seeds. Changes are relative to the no-attack baseline and are expressed in **percentage points**.

| Payment amount | No attack | Random | Greedy General | SPCR-Max | Joint SPCR-Max |
|---:|---:|---:|---:|---:|---:|
| 10,000 sats | 87.250% | 87.153% | 87.159% | 87.146% | 87.144% |
| 100,000 sats | 32.353% | 32.253% | 32.247% | 32.210% | 32.206% |
| 1,000,000 sats | 6.195% | 6.174% | 6.156% | 6.123% | 6.125% |

Change in success relative to the no-attack baseline, in percentage points:

| Payment amount | Random | Greedy General | SPCR-Max | Joint SPCR-Max |
|---:|---:|---:|---:|---:|
| 10,000 sats | −0.098 | −0.092 | −0.104 | −0.106 |
| 100,000 sats | −0.101 | −0.106 | −0.144 | −0.148 |
| 1,000,000 sats | −0.021 | −0.040 | −0.073 | −0.071 |

The main takeaway is that the tested strategies changed modeled honest-payment success only slightly, even though their attack-side congestion scores differed more noticeably. Values are rounded to three decimal places.

These results apply to this simulation setup, not the live Lightning Network. Balances are modeled, and the simulator does not fully reproduce real fees, HTLC-slot limits, timeouts, or live routing behavior.

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
