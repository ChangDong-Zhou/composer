# Copyright 2022 MosaicML Composer authors
# SPDX-License-Identifier: Apache-2.0

import os
import subprocess
import sys
import textwrap
from typing import List, Sequence
from unittest.mock import Mock

import pytest

import composer
from composer.algorithms import SelectiveBackprop
from composer.core import Engine, Event
from composer.core.algorithm import Algorithm
from composer.core.callback import Callback
from composer.core.state import State
from composer.loggers import Logger


@pytest.fixture
def always_match_algorithms():
    return [
        Mock(**{
            'match.return.value': True,
            'apply.return_value': n,  # return encodes order
        }) for n in range(5)
    ]


@pytest.fixture()
def dummy_logger(dummy_state: State):
    return Logger(dummy_state)


@pytest.fixture
def never_match_algorithms():
    attrs = {'match.return_value': False}
    return [Mock(**attrs) for _ in range(5)]


def run_event(event: Event, state: State, logger: Logger):
    runner = Engine(state, logger)
    return runner.run_event(event)


@pytest.mark.parametrize('event', list(Event))
class TestAlgorithms:

    def test_algorithms_always_called(self, event: Event, dummy_state: State, always_match_algorithms: List[Algorithm],
                                      dummy_logger: Logger):
        dummy_state.algorithms = always_match_algorithms
        _ = run_event(event, dummy_state, dummy_logger)
        for algo in always_match_algorithms:
            algo.apply.assert_called_once()
            algo.match.assert_called_once()

    def test_algorithms_never_called(self, event: Event, dummy_state: State, never_match_algorithms: List[Algorithm],
                                     dummy_logger: Logger):
        dummy_state.algorithms = never_match_algorithms
        _ = run_event(event, dummy_state, dummy_logger)
        for algo in never_match_algorithms:
            algo.apply.assert_not_called()
            algo.match.assert_called_once()

    def test_engine_trace_all(self, event: Event, dummy_state: State, always_match_algorithms: List[Algorithm],
                              dummy_logger: Logger):
        dummy_state.algorithms = always_match_algorithms
        trace = run_event(event, dummy_state, dummy_logger)

        assert all([tr.run for tr in trace.values()])

    def test_engine_trace_never(self, event: Event, dummy_state: State, never_match_algorithms: List[Algorithm],
                                dummy_logger: Logger):
        dummy_state.algorithms = never_match_algorithms
        trace = run_event(event, dummy_state, dummy_logger)

        assert all([tr.run is False for tr in trace.values()])


@pytest.mark.parametrize('event', [
    Event.EPOCH_START,
    Event.BEFORE_LOSS,
    Event.BEFORE_BACKWARD,
])
def test_engine_lifo_first_in(event: Event, dummy_state: State, dummy_logger: Logger,
                              always_match_algorithms: List[Algorithm]):
    dummy_state.algorithms = always_match_algorithms
    trace = run_event(event, dummy_state, dummy_logger)
    order = [tr.order for tr in trace.values()]
    expected_order = [tr.exit_code for tr in trace.values()]  # use exit_code to uniquely label algos

    assert order == expected_order


@pytest.mark.parametrize('event', [
    Event.AFTER_LOSS,
    Event.AFTER_BACKWARD,
    Event.BATCH_END,
])
def test_engine_lifo_last_out(event: Event, dummy_state: State, always_match_algorithms: List[Algorithm],
                              dummy_logger: Logger):
    dummy_state.algorithms = always_match_algorithms
    trace = run_event(event, dummy_state, dummy_logger)
    order = [tr.order for tr in trace.values()]
    expected_order = list(reversed([tr.exit_code for tr in trace.values()]))

    assert order == expected_order


def test_engine_with_selective_backprop(always_match_algorithms: Sequence[Algorithm], dummy_logger: Logger,
                                        dummy_state: State):
    sb = SelectiveBackprop(start=0.5, end=0.9, keep=0.5, scale_factor=0.5, interrupt=2)
    sb.apply = Mock(return_value='sb')
    sb.match = Mock(return_value=True)

    event = Event.INIT  # doesn't matter for this test

    algorithms = list(always_match_algorithms[0:2]) + [sb] + list(always_match_algorithms[2:])
    dummy_state.algorithms = algorithms

    trace = run_event(event, dummy_state, dummy_logger)

    expected = ['sb', 0, 1, 2, 3, 4]
    actual = [tr.exit_code for tr in trace.values()]

    assert actual == expected


def test_engine_is_dead_after_close(dummy_state: State, dummy_logger: Logger):
    # Create the trainer and run an event
    engine = Engine(dummy_state, dummy_logger)
    engine.run_event(Event.INIT)

    # Close it
    engine.close()

    # Assert it complains if you try to run another event
    with pytest.raises(RuntimeError):
        engine.run_event(Event.FIT_START)


class IsClosedCallback(Callback):

    def __init__(self) -> None:
        self.is_closed = False

    def close(self, state: State, logger: Logger) -> None:
        self.is_closed = True


def test_engine_closes_on_del(dummy_state: State, dummy_logger: Logger):
    # Create the trainer and run an event
    is_closed_callback = IsClosedCallback()
    dummy_state.callbacks.append(is_closed_callback)
    engine = Engine(dummy_state, dummy_logger)
    engine.run_event(Event.INIT)

    # Assert that there is just 2 -- once above, and once as the arg temp reference
    assert sys.getrefcount(engine) == 2

    # Implicitely close the engine
    del engine

    # Assert it is closed
    assert is_closed_callback.is_closed


def check_output(proc: subprocess.CompletedProcess):
    # Check the subprocess output, and raise an exception with the stdout/stderr dump if there was a non-zero exit
    # The `check=True` flag available in `subprocess.run` does not print stdout/stderr
    if proc.returncode == 0:
        return
    error_msg = textwrap.dedent(f"""\
        Command {proc.args} failed with exit code {proc.returncode}.
        ----Begin stdout----
        {proc.stdout}
        ----End stdout------
        ----Begin stderr----
        {proc.stderr}
        ----End stderr------""")

    raise RuntimeError(error_msg)


@pytest.mark.timeout(30)
@pytest.mark.parametrize("exception", [True, False])
def test_engine_closes_on_atexit(exception: bool):
    # Running this test via a subprocess, as atexit() must trigger

    code = textwrap.dedent("""\
    from composer import Trainer, Callback
    from tests.common import SimpleModel

    class CallbackWithConditionalCloseImport(Callback):
        def post_close(self):
            import requests

    model = SimpleModel(3, 10)
    cb = CallbackWithConditionalCloseImport()
    trainer = Trainer(
        model=model,
        callbacks=[cb],
        max_duration="1ep",
        train_dataloader=None,
    )
    """)
    if exception:
        # Should raise an exception, since no dataloader was provided
        code += "trainer.fit()"

    git_root_dir = os.path.join(os.path.dirname(composer.__file__), "..")
    proc = subprocess.run(["python", "-c", code], cwd=git_root_dir, text=True, capture_output=True)
    if exception:
        # manually validate that there was no a conditional import exception
        assert "ImportError: sys.meta_path is None, Python is likely shutting down" not in proc.stderr
    else:
        check_output(proc)
