# Post-W model certification — guard-pass-rate under production flags

## qwen3:14b: swap 5/7 | rejected 1 | other 1
- fit_conflict: **prose_swap** (12.7s)
  > YES, $3,500 is enough for training LLMs. [1] has 8GB VRAM, 32GB RAM, and a fast 1TB SSD — enough to fine-tune 7B-param models and keep large datasets in memory. If you go higher, consider a desktop workstation with 24GB+
- knowledge: **prose_swap** (5.9s)
  > For AI work, the main difference is memory capacity. An 8GB GPU can handle smaller models and datasets, while a 16GB GPU allows for larger models, more complex computations, and better performance with bigger datasets. T
- game_fit: **prose_swap** (6.1s)
  > YES, the Dell G16 7630 [2] is the top pick for Valorant under $1,900. Its RTX 4070 GPU delivers smooth 1080p gameplay at high settings, and the 240Hz display ensures responsive, lag-free action in fast-paced games like V
- ai_honesty: **guard_rejected** (10.2s) viol=['ungrounded_product']
- payment: **prose_swap** (12.3s)
  > No, we don’t offer payment plans, instalments, financing, leasing, or trade-in options. However, I can connect you with a human account manager to help finalize your order for multiple machines within your $25,000 budget
- budget_yn: **prose_swap** (10.1s)
  > YES. The [2] Dell G16 7630 with an RTX 4070 handles 1080p high settings at 80+ FPS in most AAA games, and its 240Hz display keeps things smooth during fast action. The [3] MSI Katana 15 with an RTX 4070 is also a great p
- game_steam: **no_job** (0.4s)

## gemma3:12b: swap 4/7 | rejected 2 | other 1
- fit_conflict: **prose_swap** (15.6s)
  > YES, $3,500 should cover a capable AI workstation. The Alienware [1] fits your budget and has 32GB of RAM, which helps prevent slowdowns when working with large datasets in Jupyter notebooks. If you exceed that budget, c
- knowledge: **guard_rejected** (7.2s) viol=['ungrounded_spec']
- game_fit: **prose_swap** (8.4s)
  > YES, the Lenovo LOQ 15IRH8 [1] fits your budget and gaming needs. Its RTX 4060 GPU will easily handle Valorant at high frame rates, plus it has 16GB of RAM for smooth multitasking. The Dell G16 [2] offers a faster screen
- ai_honesty: **guard_rejected** (14.5s) viol=['ungrounded_product']
- payment: **prose_swap** (12.3s)
  > NO, we don't offer payment plans or financing of any kind. For orders over $20,000, I can bring in an account manager who can discuss your needs further; would you like me to do that?
- budget_yn: **prose_swap** (11.9s)
  > YES, $1,800 is plenty for a solid gaming laptop. The [2] Dell G16 with its RTX 4070 will run Cyberpunk at 60 FPS on High settings—a noticeable upgrade over the [1] Lenovo's RTX 4060 which might require slightly lower set
- game_steam: **no_job** (0.4s)
