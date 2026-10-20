# SCOOP-Simulation: Payment-Channel Congestion Research Prototype

A Python research simulator for exploring congestion attacks in the Bitcoin Lightning Network. It compares attack strategies on synthetic networks or a historical Lightning topology, then measures their effects on ordinary payment success. The saved results use the historical topology.

This is an independent, SCOOP-inspired research prototype, not the paper authors' official implementation or a reproduction of their results. It does not interact with live Lightning nodes. Historical channel balances are not public in the snapshot, so balances in these experiments are **modeled, not observed**.

## Relation to the SCOOP paper

**Taken from the paper** (Ababneh, Kolachala and Vishwanathan, 2025):

- The PCR and SPCR congestion metrics (Definitions 4.2 and 4.3).
- The congestion-maximization attack, SPCR Max (Eqs. 9–12), solved for each sender in turn on the balances left by earlier senders (Algorithm 2).
- The Random and General congestion attacks that the paper uses as baselines (Section 5).
- The main parameters: 6 attacker pairs (12 Sybil nodes), budgets of 75M and 100M satoshis, and paths of at most 8 channels.

**Added in this project:**

- **Joint SPCR-Max.** The paper's linear program has no constraint for routes that share a channel; the paper updates shared capacities one path at a time. This variant adds that constraint inside each sender's linear program.
- **Honest-payment success.** SCOOP evaluates attack-side metrics only. Measuring how the attacks affect ordinary payments is this project's own question.
- **A historical topology.** The paper uses random channel capacities with a mean of 4M satoshis and does not say which topology it uses. This project uses the 27 November 2021 Lightning snapshot with modeled balances.

**Not implemented:** the paper's first attack, payment minimization (MinPay, Section 4.3.1).

The paper averages 200 iterations with a mean path length of 6 channels; the run here uses 20 seeds and a mean path length of 5.90 channels. The numbers below are not directly comparable with the paper's figures.

## What it compares

- **No attack**: baseline for legitimate payments.
- **Random**: spends a random amount up to the budget, split across candidate routes with random weights.
- **Greedy General**: fills the routes with the largest current bottlenecks first, until the budget runs out.
- **SPCR-Max**: solves the paper's linear program for each sender, then applies the payments in route order, capping them where routes share a channel. Budget lost to that capping is not reallocated.
- **Joint SPCR-Max**: the same linear program with the shared-channel constraint described above.

The simulator records locked payment value, PCR/SPCR congestion scores, and honest-payment success. PCR compares each route's own payment with that route's bottleneck before the attack. See `scoop/` for the implementation and `results_real_full_diverse/` for the full experiment outputs.

## Results

The full historical-topology run completed **120 scenarios across 20 random seeds**, producing 600 strategy-level result rows. It tested five strategies, two per-sender budgets (75M and 100M satoshis), and three payment sizes (10,000, 100,000, and 1,000,000 satoshis). The snapshot has 18,310 nodes and 80,743 channels. After removing channels with a missing or disabled routing policy, merging parallel channels between the same two nodes, and keeping the largest connected component, the processed topology contained **12,314 nodes and 57,790 channels**.

### Attack-related metrics

Means across 20 seeds. Locked payment is shown in millions of satoshis; balances are modeled. PCR and SPCR-8 are the simulator's route-set congestion scores. SPCR-8 uses L_max = 8. The paper states L_max = 20 hops, but with routes of at most 8 channels SPCR could not exceed 0.4 under that value, while the paper's Fig. 5b reaches about 0.57. `raw_results.csv` also reports SPCR with L_max = 20.

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

Joint SPCR-Max had the highest mean SPCR-8 score among the tested attack strategies at both budgets, and in each of the 40 seed-budget runs. These are simulated congestion metrics, not real funds or observed network behavior.

Two results need care when comparing with the paper:

- **Random scored above Greedy General** on PCR and SPCR-8 in 39 of the 40 runs; in the paper's Fig. 5, General scores above Random. Greedy General put its budget into the largest routes and paid into about 740–775 of the 1,634 candidate routes, against about 1,440–1,455 for Random. A one-seed check (seed 0, 75M budget) measured how much of each route's honest-hop capacity was used up after the whole attack, and gave the same order: Joint SPCR-Max 0.98, SPCR-Max 0.98, Random 0.75, Greedy General 0.64. The cause of the difference from the paper has not been isolated.
- **The budget was not always the limit.** The three non-random strategies locked 55–69M satoshis per sender on average, below the 75M and 100M budgets. In the seed-0 check, three of the six senders had candidate routes whose bottlenecks added up to only 46–67M satoshis, less than the 75M budget, and the three non-random strategies locked similar amounts for them (34–50M). Part of the comparison therefore reflects route capacity rather than how the budget was allocated.

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

The drops are small but consistent: all 24 paired 95% confidence intervals in `paired_differences.csv` (strategy × budget × payment size) lie below zero. Two facts help read their size. Without an attack, only 87.25% of 10,000-sat, 32.35% of 100,000-sat and 6.20% of 1,000,000-sat payments succeeded, so most large payments already fail under the modeled balances and balance-blind shortest-hop routing. And the attacks fully drained only about 750 (Random, Greedy General) to 1,340 (Joint SPCR-Max) channel directions on average, roughly 1% of the 115,580 in the processed graph.

These results apply to this simulation setup, not the live Lightning Network. Balances are modeled, and the simulator does not fully reproduce real fees, HTLC-slot limits, timeouts, or live routing behavior.

Detailed data and plots are in [`results_real_full_diverse/`](results_real_full_diverse/), including `summary.csv`, `paired_differences.csv`, and `summary_report.md`.

## Run it

Python 3.11 or 3.12 is recommended (the tests also pass on 3.14).

```bash
git clone https://github.com/immohamedadhil/scoop-simulation.git
cd scoop-simulation
python -m pip install -e ".[dev]"
python -m pytest -q
```

A small synthetic smoke test:

```bash
python -m scoop.experiments --quick --nodes 50 --k-paths 5 --output results_smoke
```

To run on the historical topology, download `snapshots/lngraph_2021_11_27__00_00.json.zst` from the [TU Berlin discharged-PC data repository](https://git.tu-berlin.de/rohrer/discharged-pc-data), decompress it, and pass the resulting JSON file with `--snapshot`. The dataset is not included in this repository. The default settings match the saved run:

```bash
python scripts/decompress_snapshot.py lngraph_2021_11_27__00_00.json.zst data/lngraph_2021_11_27__00_00.json
python -m scoop.experiments --snapshot data/lngraph_2021_11_27__00_00.json --output results_real
```

## Limitations

Balances are modeled, not observed. The simulator uses a static graph and does not fully model real fees, HTLC-slot limits, timeouts, or live routing behavior. Results depend on the selected topology, routing settings, balance model, and assumptions.

The 20 seeds change only the modeled balances and the honest-payment workload. The Sybil nodes always attach to the same 12 highest-degree nodes, and the route sampler's random generator does not depend on the seed, so every run uses the same 1,634 candidate routes. The confidence intervals therefore do not cover different attacker placements.

The current test suite checks software behavior; passing tests is not proof that the model represents every aspect of the live network.

## Reference

Mohammed Ababneh, Kartick Kolachala, and Roopa Vishwanathan, “SCOOP: CoSt-effective COngestiOn Attacks in Payment Channel Networks,” arXiv:2503.12625 (2025). A preliminary version appeared at the 6th Workshop on Coordination of Decentralized Finance (CoDecFin 2025). [Paper](https://arxiv.org/abs/2503.12625)

## License

MIT License. See [LICENSE](LICENSE).
