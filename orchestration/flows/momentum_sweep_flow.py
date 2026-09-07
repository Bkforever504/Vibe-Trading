from orchestration.flows.common import flow, run_shadow_script

@flow(name="momentum-sweep", log_prints=True)
def momentum_sweep_flow():
    return run_shadow_script("momentum_sweep_runner.py")

if __name__ == "__main__": momentum_sweep_flow()
