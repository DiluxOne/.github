"""Azure Functions entry point of the VM's clock (clock.py)."""
import logging
import os

import azure.functions as func

import clock

app = func.FunctionApp()


# Every five minutes, at second 0. use_monitor keeps the schedule's last run
# in storage, so a restart catches up instead of skipping a tick.
@app.timer_trigger(schedule="0 */5 * * * *", arg_name="timer", run_on_startup=False, use_monitor=True)
def runner_vm_clock(timer: func.TimerRequest) -> None:
    status = clock.tick(os.environ)
    logging.info("runner-vm.yml dispatched with auto: HTTP %s", status)
