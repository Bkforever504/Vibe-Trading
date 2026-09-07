from orchestration.flows.common import flow, run_shadow_script

@flow(name="shadow-system-heartbeat", log_prints=True)
def shadow_system_heartbeat_flow():
    return run_shadow_script("shadow_system_heartbeat.py")

if __name__ == "__main__": shadow_system_heartbeat_flow()
