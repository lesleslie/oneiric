"""Tests for BaseMagics."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from oneiric.shell.magics import BaseMagics


@pytest.fixture
def ipython_shell():
    """Create a mock IPython shell compatible with traitlets."""
    with patch("oneiric.shell.magics.Magics.__init__", lambda self, shell: None):
        magics = BaseMagics.__new__(BaseMagics)
        magics.app = None
        magics.shell = MagicMock()
        magics.shell.__version__ = "8.0"
        return magics


class TestBaseMagics:
    def test_set_app(self, ipython_shell):
        app = MagicMock()
        ipython_shell.set_app(app)
        assert ipython_shell.app is app

    def test_help_shell_magic(self, capsys, ipython_shell):
        ipython_shell.help_shell("")
        output = capsys.readouterr().out
        assert "Admin Shell Commands" in output
        assert "%help_shell" in output
        assert "%status" in output

    def test_status_magic_with_app(self, capsys, ipython_shell):
        app = MagicMock()
        app.__class__.__name__ = "TestApp"
        ipython_shell.set_app(app)
        ipython_shell.status("")
        output = capsys.readouterr().out
        assert "TestApp" in output
        assert "8.0" in output

    def test_status_magic_no_app(self, capsys, ipython_shell):
        ipython_shell.status("")
        output = capsys.readouterr().out
        assert "None" in output

    def test_status_magic_no_version(self, capsys, ipython_shell):
        del ipython_shell.shell.__version__
        ipython_shell.status("")
        output = capsys.readouterr().out
        assert "unknown" in output
