from orchestration.flows.common import flow, run_shadow_script

@flow(name="pattern-grader", log_prints=True)
def pattern_grader_flow():
    return run_shadow_script("pattern_grader_scanner.py")

if __name__ == "__main__": pattern_grader_flow()
