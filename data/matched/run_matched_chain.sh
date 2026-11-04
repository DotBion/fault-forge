#!/bin/bash
# resumable chain: matched arms -> oneshot arm -> comparison. Re-run safely after an interruption.
cd /workspace/faultforge
unset FF_SAT_RULE FF_POLICY
N=(232 300 300)
for arm in matchfam matchall; do for s in 0 1 2; do
  nice -n 10 python3 src/matched_search.py --arm $arm --seed $s --n ${N[$s]} --workers 3 || exit 1
done; done
for s in 0 1 2; do
  [ -f data/matched/oneshot_seed${s}_bank.json ] || python3 src/oneshot_search.py bank --seed $s --bank 40 || continue
  nice -n 10 python3 src/oneshot_search.py run --seed $s --n ${N[$s]} --workers 3
done
nice -n 10 python3 src/matched_compare.py --workers 3
echo CHAIN_DONE
