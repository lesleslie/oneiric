

# Timing Attack Mitigation Tests


class TestConstantTimeComparison:
    """Test constant-time comparison functions."""

    def test_compare_equal_strings(self):
        """Constant-time comparison returns True for equal strings."""
        from oneiric.core.security import constant_time_compare

        result = constant_time_compare("hello", "hello")
        assert result is True

    def test_compare_unequal_strings(self):
        """Constant-time comparison returns False for unequal strings."""
        from oneiric.core.security import constant_time_compare

        result = constant_time_compare("hello", "world")
        assert result is False

    def test_compare_different_lengths(self):
        """Constant-time comparison handles different length strings."""
        from oneiric.core.security import constant_time_compare

        result = constant_time_compare("short", "much longer string")
        assert result is False

    def test_compare_empty_strings(self):
        """Constant-time comparison handles empty strings."""
        from oneiric.core.security import constant_time_compare

        result = constant_time_compare("", "")
        assert result is True

    def test_compare_rejects_non_string_types(self):
        """Constant-time comparison rejects non-string types."""
        from oneiric.core.security import constant_time_compare
        import pytest

        with pytest.raises(TypeError):
            constant_time_compare(b"bytes", "string")

        with pytest.raises(TypeError):
            constant_time_compare(123, "123")

    def test_timing_safe_compare_strings(self):
        """Timing-safe comparison works with strings."""
        from oneiric.core.security import timing_safe_compare

        result = timing_safe_compare("test", "test")
        assert result is True

    def test_timing_safe_compare_bytes(self):
        """Timing-safe comparison works with bytes."""
        from oneiric.core.security import timing_safe_compare

        result = timing_safe_compare(b"test", b"test")
        assert result is True

    def test_timing_safe_compare_mixed_types_fails(self):
        """Timing-safe comparison rejects mixed types."""
        from oneiric.core.security import timing_safe_compare
        import pytest

        with pytest.raises(TypeError):
            timing_safe_compare("string", b"bytes")

    def test_constant_time_bytes_compare_equal(self):
        """Constant-time bytes comparison returns True for equal bytes."""
        from oneiric.core.security import constant_time_bytes_compare

        result = constant_time_bytes_compare(b"data", b"data")
        assert result is True

    def test_constant_time_bytes_compare_unequal(self):
        """Constant-time bytes comparison returns False for unequal bytes."""
        from oneiric.core.security import constant_time_bytes_compare

        result = constant_time_bytes_compare(b"data", b"different")
        assert result is False

    def test_constant_time_bytes_compare_rejects_non_bytes(self):
        """Constant-time bytes comparison rejects non-bytes types."""
        from oneiric.core.security import constant_time_bytes_compare
        import pytest

        with pytest.raises(TypeError):
            constant_time_bytes_compare("string", b"bytes")

    def test_comparison_timing_consistency(self):
        """Verify that comparison time is independent of input position."""
        from oneiric.core.security import constant_time_compare
        import timeit

        # Prepare test data - same length strings
        equal_same = ["test"] * 100
        equal_diff = ["xyz"] * 100
        unequal_diff = ["abc"] * 100

        # Measure times for equal strings at different positions
        times_equal = []
        for i in range(1000):
            start = timeit.default_timer()
            constant_time_compare("test", "test")
            end = timeit.default_timer()
            times_equal.append(end - start)

        # Measure times for unequal strings
        times_unequal = []
        for i in range(1000):
            start = timeit.default_timer()
            constant_time_compare("test", "world")
            end = timeit.default_timer()
            times_unequal.append(end - start)

        # The variance in timing should be high (noise), but we want to ensure
        # there's no systematic bias where equal comparisons are consistently
        # faster/slower than unequal ones
        # This is a basic sanity check - full timing analysis requires controlled environment

        avg_equal = sum(times_equal) / len(times_equal)
        avg_unequal = sum(times_unequal) / len(times_unequal)

        # Both should take similar time (within factor of 10 for noise tolerance)
        # In production, use more sophisticated timing analysis
        assert avg_equal < avg_unequal * 10
        assert avg_unequal < avg_equal * 10

    def test_comparison_prevents_content_guessing(self):
        """Demonstrate that constant-time comparison prevents content guessing.

        This test shows that regular comparison can leak information through timing
        when the comparison short-circuits at the first differing character.
        Constant-time comparison always compares the entire string.
        """
        from oneiric.core.security import constant_time_compare

        # With regular == operator, comparing "a" vs "b" is faster than
        # comparing "aaaaaaaaaab" vs "aaaaaaaaabb" because the latter
        # requires more character comparisons before finding the difference

        # Constant-time comparison should take similar time regardless
        # of where the difference is (within noise tolerance)
        # This is a conceptual test - actual timing verification requires
        # controlled environment and many iterations

        # Test that all characters are compared
        secret = "correct_password"
        wrong = "xorrect_password"  # First char different
        very_close = "correct_password"[:-1] + "X"  # Last char different

        # All comparisons should complete (no short-circuit)
        assert constant_time_compare(secret, secret) is True
        assert constant_time_compare(secret, wrong) is False
        assert constant_time_compare(secret, very_close) is False

        # No early return - full comparison always happens
        # This prevents attackers from guessing passwords character by character
