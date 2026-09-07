from orchestration.flows.common import flow, run_shadow_script

@flow(name="blsh-forward-return-joiner", log_prints=True)
def blsh_fwd_return_joiner_flow(bars_path: str):
    return run_shadow_script("blsh_outcome_shadow.py", "--bars", bars_path)

if __name__ == "__main__":
    raise SystemExit("Pass bars_path from a Prefect deployment; no data path is guessed.")
