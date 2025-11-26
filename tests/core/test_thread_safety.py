"""Thread safety tests for CandidateRegistry.

These tests verify that the candidate registry is thread-safe and can handle
concurrent operations without race conditions or data corruption.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from oneiric.core.resolution import Candidate, CandidateRegistry, CandidateSource


class TestCandidateRegistryThreadSafety:
    """Test thread safety of CandidateRegistry operations."""

    def test_concurrent_registrations_no_data_loss(self):
        """Concurrent registrations don't lose data."""
        registry = CandidateRegistry()
        num_threads = 10
        registrations_per_thread = 100

        def register_candidates(thread_id: int):
            """Register candidates from a thread."""
            for i in range(registrations_per_thread):
                candidate = Candidate(
                    domain="adapter",
                    key=f"cache-{thread_id}-{i}",
                    provider=f"provider-{thread_id}",
                    factory=lambda: None,
                    source=CandidateSource.MANUAL,
                )
                registry.register_candidate(candidate)

        # Run concurrent registrations
        threads = []
        for tid in range(num_threads):
            thread = threading.Thread(target=register_candidates, args=(tid,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Verify all candidates were registered
        # Each thread registers candidates with unique keys
        expected_count = num_threads * registrations_per_thread
        actual_count = len(registry._candidates)

        assert actual_count == expected_count, f"Expected {expected_count} unique keys, got {actual_count}"

    def test_concurrent_registrations_same_key(self):
        """Concurrent registrations for the same key handled correctly."""
        registry = CandidateRegistry()
        num_threads = 20
        domain = "adapter"
        key = "cache"

        def register_candidate(thread_id: int):
            """Register a candidate for the same key."""
            candidate = Candidate(
                domain=domain,
                key=key,
                provider=f"provider-{thread_id}",
                factory=lambda: None,
                priority=thread_id,  # Different priorities
                source=CandidateSource.MANUAL,
            )
            registry.register_candidate(candidate)

        # Run concurrent registrations
        threads = []
        for tid in range(num_threads):
            thread = threading.Thread(target=register_candidate, args=(tid,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Verify all candidates were registered (same key, multiple providers)
        candidates = registry._candidates.get((domain, key), [])
        assert len(candidates) == num_threads

        # Verify active candidate was selected (highest priority)
        active = registry.resolve(domain, key)
        assert active is not None
        assert active.priority == num_threads - 1  # Highest priority wins

    def test_concurrent_resolve_operations(self):
        """Concurrent resolve operations return consistent results."""
        registry = CandidateRegistry()

        # Register a candidate
        candidate = Candidate(
            domain="adapter",
            key="cache",
            provider="redis",
            factory=lambda: None,
            source=CandidateSource.MANUAL,
        )
        registry.register_candidate(candidate)

        num_threads = 50
        results = []
        results_lock = threading.Lock()

        def resolve_candidate():
            """Resolve candidate from a thread."""
            resolved = registry.resolve("adapter", "cache")
            with results_lock:
                results.append(resolved)

        # Run concurrent resolves
        threads = []
        for _ in range(num_threads):
            thread = threading.Thread(target=resolve_candidate)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Verify all threads got the same result
        assert len(results) == num_threads
        # All threads should get the same candidate instance (not None)
        assert all(r is not None for r in results)
        # All results should be the same instance (identity check)
        assert all(r is results[0] for r in results)
        # Check provider matches
        assert all(r.provider == "redis" for r in results)

    def test_concurrent_list_operations(self):
        """Concurrent list operations don't corrupt data."""
        registry = CandidateRegistry()

        # Register some candidates
        for i in range(10):
            candidate = Candidate(
                domain="adapter",
                key=f"cache-{i}",
                provider=f"provider-{i}",
                factory=lambda: None,
                source=CandidateSource.MANUAL,
            )
            registry.register_candidate(candidate)

        num_threads = 30
        results = []
        results_lock = threading.Lock()

        def list_active():
            """List active candidates from a thread."""
            active = registry.list_active("adapter")
            with results_lock:
                results.append(len(active))

        # Run concurrent list operations
        threads = []
        for _ in range(num_threads):
            thread = threading.Thread(target=list_active)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Verify all threads got consistent results
        assert len(results) == num_threads
        assert all(count == 10 for count in results)

    def test_concurrent_registration_and_resolution(self):
        """Concurrent registrations and resolutions work correctly."""
        registry = CandidateRegistry()
        num_operations = 100

        def register_and_resolve(op_id: int):
            """Register then resolve a candidate."""
            # Register
            candidate = Candidate(
                domain="service",
                key=f"worker-{op_id}",
                provider=f"provider-{op_id}",
                factory=lambda: None,
                source=CandidateSource.MANUAL,
            )
            registry.register_candidate(candidate)

            # Resolve
            resolved = registry.resolve("service", f"worker-{op_id}")
            assert resolved is not None
            assert resolved.provider == f"provider-{op_id}"

        # Run concurrent operations
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(register_and_resolve, i) for i in range(num_operations)]

            # Wait for all to complete
            for future in as_completed(futures):
                future.result()  # Raises exception if operation failed

    def test_concurrent_explain_operations(self):
        """Concurrent explain operations return consistent results."""
        registry = CandidateRegistry()

        # Register multiple candidates for same key
        for i in range(5):
            candidate = Candidate(
                domain="adapter",
                key="cache",
                provider=f"provider-{i}",
                factory=lambda: None,
                priority=i,
                source=CandidateSource.MANUAL,
            )
            registry.register_candidate(candidate)

        num_threads = 20
        results = []
        results_lock = threading.Lock()

        def explain_resolution():
            """Explain resolution from a thread."""
            explanation = registry.explain("adapter", "cache")
            with results_lock:
                results.append((explanation.winner.provider if explanation.winner else None, len(explanation.ordered)))

        # Run concurrent explains
        threads = []
        for _ in range(num_threads):
            thread = threading.Thread(target=explain_resolution)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Verify all threads got consistent results
        assert len(results) == num_threads
        winner_providers = [r[0] for r in results]
        ordered_counts = [r[1] for r in results]

        # All threads should see the same winner (highest priority)
        assert all(provider == "provider-4" for provider in winner_providers)
        # All threads should see the same number of candidates
        assert all(count == 5 for count in ordered_counts)

    def test_sequence_counter_thread_safe(self):
        """Sequence counter increments correctly under concurrency."""
        registry = CandidateRegistry()
        num_threads = 20
        registrations_per_thread = 50

        def register_candidates(thread_id: int):
            """Register candidates from a thread."""
            for i in range(registrations_per_thread):
                candidate = Candidate(
                    domain="task",
                    key=f"job-{thread_id}-{i}",
                    provider="worker",
                    factory=lambda: None,
                    source=CandidateSource.MANUAL,
                )
                registry.register_candidate(candidate)

        # Run concurrent registrations
        threads = []
        for tid in range(num_threads):
            thread = threading.Thread(target=register_candidates, args=(tid,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Verify sequence counter is correct
        expected_sequence = num_threads * registrations_per_thread
        assert registry._sequence == expected_sequence

        # Verify all candidates have unique sequences
        all_sequences = set()
        for candidates in registry._candidates.values():
            for candidate in candidates:
                if candidate.registry_sequence:
                    all_sequences.add(candidate.registry_sequence)

        assert len(all_sequences) == expected_sequence

    def test_no_deadlocks_with_reentrant_lock(self):
        """Reentrant lock allows same thread to acquire multiple times."""
        registry = CandidateRegistry()

        # This should NOT deadlock because we use RLock
        def nested_operation():
            """Operation that triggers nested lock acquisition."""
            candidate = Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: None,
                source=CandidateSource.MANUAL,
            )
            # register_candidate acquires lock, then calls _recompute which calls
            # _score_candidates (all under same lock - should work with RLock)
            registry.register_candidate(candidate)

            # This also acquires the lock (nested)
            resolved = registry.resolve("adapter", "cache")
            assert resolved is not None

        # Run in a thread to ensure it completes without deadlock
        thread = threading.Thread(target=nested_operation)
        thread.start()
        thread.join(timeout=2.0)  # Should complete quickly

        assert not thread.is_alive(), "Thread deadlocked!"

    def test_concurrent_mixed_operations(self):
        """Mixed read/write operations under high concurrency."""
        registry = CandidateRegistry()

        # Pre-register some candidates
        for i in range(10):
            candidate = Candidate(
                domain="adapter",
                key=f"cache-{i}",
                provider=f"provider-{i}",
                factory=lambda: None,
                source=CandidateSource.MANUAL,
            )
            registry.register_candidate(candidate)

        num_operations = 200
        errors = []
        errors_lock = threading.Lock()

        def mixed_operation(op_id: int):
            """Perform mixed read/write operations."""
            try:
                if op_id % 4 == 0:
                    # Register new candidate
                    candidate = Candidate(
                        domain="service",
                        key=f"worker-{op_id}",
                        provider="worker",
                        factory=lambda: None,
                        source=CandidateSource.MANUAL,
                    )
                    registry.register_candidate(candidate)
                elif op_id % 4 == 1:
                    # Resolve existing
                    key_idx = op_id % 10
                    registry.resolve("adapter", f"cache-{key_idx}")
                elif op_id % 4 == 2:
                    # List active
                    registry.list_active("adapter")
                else:
                    # Explain
                    key_idx = op_id % 10
                    registry.explain("adapter", f"cache-{key_idx}")
            except Exception as e:
                with errors_lock:
                    errors.append((op_id, str(e)))

        # Run concurrent mixed operations
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(mixed_operation, i) for i in range(num_operations)]

            for future in as_completed(futures):
                future.result()  # Collect any exceptions

        # No errors should occur
        assert len(errors) == 0, f"Errors occurred: {errors}"


class TestResolverThreadSafety:
    """Test thread safety of Resolver facade."""

    def test_resolver_inherits_thread_safety(self):
        """Resolver operations are thread-safe through CandidateRegistry."""
        from oneiric.core.resolution import Resolver

        resolver = Resolver()
        num_threads = 20

        def register_and_resolve(thread_id: int):
            """Register and resolve through Resolver."""
            candidate = Candidate(
                domain="adapter",
                key=f"cache-{thread_id}",
                provider=f"provider-{thread_id}",
                factory=lambda: None,
                source=CandidateSource.MANUAL,
            )
            resolver.register(candidate)

            resolved = resolver.resolve("adapter", f"cache-{thread_id}")
            assert resolved is not None
            assert resolved.provider == f"provider-{thread_id}"

        # Run concurrent operations through Resolver
        threads = []
        for tid in range(num_threads):
            thread = threading.Thread(target=register_and_resolve, args=(tid,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Verify all candidates were registered
        active = resolver.list_active("adapter")
        assert len(active) == num_threads
