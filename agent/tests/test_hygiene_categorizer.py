from scripts.hygiene.apply_gitignore_updates import updated
from scripts.hygiene.categorize_working_tree import classify, status_entries


def test_status_parser_preserves_spaces_and_rename_destination():
    assert status_entries('?? docs/My File.md\nR  old.py -> new.py\n') == [
        ('??', 'docs/My File.md'), ('R ', 'new.py')]


def test_secret_and_cache_categories_win_over_workstream():
    assert classify('agent/.env.local') == 'secret_candidate'
    assert classify('agent/analytics/__pycache__/x.pyc') == 'pytest_cache'


def test_cv_and_unknown_meaningful_categories():
    assert classify('agent/governance/statistical_gate.py') == 'workstream_ws_cv_bootstrap'
    assert classify('scripts/custom.py') == 'workstream_unknown_but_meaningful'


def test_gitignore_update_is_additive_and_idempotent():
    once, missing = updated('existing/\n')
    twice, second_missing = updated(once)
    assert missing and 'existing/' in once
    assert twice == once
    assert second_missing == []
