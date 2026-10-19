# SCOOP-inspired simulation report

## Setup

- Network input: data/lngraph_2021_11_27__00_00.json
- Balance model: uniform; balances are **modeled, not observed**.
- Seeds: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19
- Route mode: sender_to_all_receivers
- Budget scope: per sender
- Budget per owner (satoshi): 75,000,000, 100,000,000
- Honest payment amounts (satoshi): 10,000, 100,000, 1,000,000
- Strategies: greedy_general, joint_spcr_max, no_attack, random, spcr_max

## Observed results

Mean honest payment success rate across the completed rows:

| Scenario | Mean honest success rate |
|---|---:|
| no_attack | 0.4193 |
| random | 0.4186 |
| greedy_general | 0.4185 |
| spcr_max | 0.4183 |
| joint_spcr_max | 0.4182 |

See `raw_results.csv` for the individual seed results, `summary.csv` for means and 95% confidence intervals, and `paired_differences.csv` for attack-minus-no-attack effects paired by seed.

## Modeling choices and limitations

This is a simulation on a static topology inspired by SCOOP; it is not a reproduction of SCOOP and does not interact with a live Lightning node. Channel balances are generated because the real balances are private. The `sender_to_all_receivers` mode models six sender Sybils and six receiver Sybils; each sender shares one budget across routes to all receivers. The paper's exact route enumeration and balance split are not fully specified, so `fixed_pairs` remains available as a sensitivity baseline. The topology loader excludes a physical channel if either directional policy is missing or disabled. Honest payments use shortest-hop routing with retries that exclude a failed directed hop. Fees, HTLC slot limits, and timeouts are not modeled, and attacker locks remain in place during honest workload measurements. Each strategy uses the same pre-generated honest workload and a matching no-attack baseline for its seed, budget, and payment amount.

Attack-side PCR and SPCR are reported separately from honest-payment success. `honest_coin_hops_stuck` is an aggregate over route interiors, not a count of unique coins, because overlapping routes can count the same channel more than once. Do not tune parameters to match the paper's numbers. Treat differences between strategies and between congestion metrics and honest payment failures as empirical findings.
