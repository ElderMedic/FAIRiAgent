from fairifier.graph.state import FAIRifierState
from fairifier.graph.edges import route_after_critic, route_after_parser

def test_route_after_critic_accept():
    # Setup state with ACCEPT decision
    state: FAIRifierState = {
        "execution_history": [
            {
                "critic_evaluation": {
                    "decision": "ACCEPT",
                    "score": 0.95
                }
            }
        ]
    }
    assert route_after_critic(state) == "finalize"

def test_route_after_critic_reject():
    # Setup state with REJECT decision
    state: FAIRifierState = {
        "execution_history": [
            {
                "critic_evaluation": {
                    "decision": "REJECT",
                    "score": 0.4
                }
            }
        ]
    }
    assert route_after_critic(state) == "orchestrate"

def test_route_after_critic_retry():
    # Setup state with RETRY decision
    state: FAIRifierState = {
        "execution_history": [
            {
                "critic_evaluation": {
                    "decision": "RETRY",
                    "score": 0.6
                }
            }
        ]
    }
    assert route_after_critic(state) == "orchestrate"

def test_route_after_critic_missing_history():
    # Setup state with no execution history
    state: FAIRifierState = {}
    assert route_after_critic(state) == "finalize"

def test_route_after_critic_missing_eval():
    # Setup state with history but missing evaluation or decision details
    state: FAIRifierState = {
        "execution_history": [{}]
    }
    assert route_after_critic(state) == "finalize"

def test_route_after_parser():
    # Parser output with no errors should orchestrate
    state_no_error: FAIRifierState = {"errors": []}
    assert route_after_parser(state_no_error) == "orchestrate"

    # Parser output with errors should finalize
    state_error: FAIRifierState = {"errors": ["parsing failed"]}
    assert route_after_parser(state_error) == "finalize"
