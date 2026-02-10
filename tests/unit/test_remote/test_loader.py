"""
Comprehensive remote manifest loader tests.

Tests remote manifest loading, signature verification, dependency resolution,
and security validation for the Oneiric remote system.
"""

import pytest
import tempfile
import json
from pathlib import Path
from unittest import mock
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ed25519

from oneiric.remote import (
    RemoteLoader,
    ManifestValidator,
    SignatureVerifier,
    ManifestError,
    SignatureError,
    ManifestNotFoundError,
    RemoteManifest,
    ManifestEntry,
)
from oneiric.remote.security import verify_signature, compute_sha256


class TestRemoteLoader:
    """Test suite for RemoteLoader class."""

    @pytest.fixture
    def loader(self):
        """Create a fresh RemoteLoader for each test."""
        return RemoteLoader()

    @pytest.fixture
    def sample_manifest(self):
        """Create a sample manifest for testing."""
        return {
            'version': '2.0',
            'metadata': {
                'name': 'test_manifest',
                'owner': 'test_owner',
                'created_at': '2025-01-01T00:00:00Z'
            },
            'adapters': [
                {
                    'name': 'cache',
                    'provider': 'redis',
                    'domain': 'cache',
                    'module_path': 'oneiric.adapters.cache.redis',
                    'version': '1.0.0',
                    'priority': 100,
                    'signature': 'test_signature',
                    'sha256': 'test_hash'
                }
            ],
            'services': [],
            'tasks': [],
            'events': [],
            'workflows': []
        }

    def test_load_manifest_from_file(self, loader, sample_manifest):
        """Test loading manifest from file."""
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        ) as f:
            json.dump(sample_manifest, f)
            temp_path = f.name

        try:
            manifest = loader.load_from_file(temp_path)
            assert manifest is not None
            assert manifest.version == '2.0'
            assert manifest.metadata['name'] == 'test_manifest'
        finally:
            Path(temp_path).unlink()

    def test_load_manifest_from_url(self, loader, sample_manifest):
        """Test loading manifest from URL."""
        with mock.patch('httpx.get') as mock_get:
            mock_response = mock.Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = sample_manifest
            mock_get.return_value = mock_response

            manifest = loader.load_from_url('https://example.com/manifest.json')
            assert manifest is not None
            assert manifest.version == '2.0'

    def test_load_manifest_file_not_found(self, loader):
        """Test loading non-existent manifest file."""
        with pytest.raises(ManifestNotFoundError):
            loader.load_from_file('/nonexistent/manifest.json')

    def test_load_manifest_invalid_json(self, loader):
        """Test loading invalid JSON manifest."""
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        ) as f:
            f.write('invalid json content')
            temp_path = f.name

        try:
            with pytest.raises(json.JSONDecodeError):
                loader.load_from_file(temp_path)
        finally:
            Path(temp_path).unlink()

    def test_load_manifest_with_validation(self, loader, sample_manifest):
        """Test loading manifest with validation."""
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        ) as f:
            json.dump(sample_manifest, f)
            temp_path = f.name

        try:
            manifest = loader.load_from_file(temp_path, validate=True)
            assert manifest is not None
        finally:
            Path(temp_path).unlink()

    def test_load_manifest_invalid_version(self, loader):
        """Test loading manifest with invalid version."""
        invalid_manifest = {
            'version': '999.0',  # Unsupported version
            'metadata': {},
            'adapters': [],
            'services': [],
            'tasks': [],
            'events': [],
            'workflows': []
        }

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        ) as f:
            json.dump(invalid_manifest, f)
            temp_path = f.name

        try:
            with pytest.raises(ManifestError):
                loader.load_from_file(temp_path, validate=True)
        finally:
            Path(temp_path).unlink()

    def test_load_manifest_empty_domains(self, loader):
        """Test loading manifest with empty domains."""
        empty_manifest = {
            'version': '2.0',
            'metadata': {'name': 'empty'},
            'adapters': [],
            'services': [],
            'tasks': [],
            'events': [],
            'workflows': []
        }

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        ) as f:
            json.dump(empty_manifest, f)
            temp_path = f.name

        try:
            manifest = loader.load_from_file(temp_path)
            assert len(manifest.adapters) == 0
            assert len(manifest.services) == 0
        finally:
            Path(temp_path).unlink()

    def test_sync_remote_manifest(self, loader, sample_manifest):
        """Test syncing remote manifest."""
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        ) as f:
            json.dump(sample_manifest, f)
            temp_path = f.name

        try:
            result = loader.sync(temp_path)
            assert result.success is True
            assert result.registrations > 0
        finally:
            Path(temp_path).unlink()

    def test_sync_with_signature_verification(self, loader, sample_manifest):
        """Test syncing with signature verification."""
        # Generate key pair
        private_key = ed25519.Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        # Sign manifest
        manifest_data = json.dumps(sample_manifest).encode()
        signature = private_key.sign(manifest_data)

        # Add signature to manifest
        sample_manifest['signature'] = signature.hex()

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        ) as f:
            json.dump(sample_manifest, f)
            temp_path = f.name

        try:
            result = loader.sync(
                temp_path,
                verify_signature=True,
                public_key=public_key
            )
            assert result.success is True
        finally:
            Path(temp_path).unlink()


class TestSignatureVerifier:
    """Test suite for SignatureVerifier class."""

    @pytest.fixture
    def verifier(self):
        """Create a SignatureVerifier instance."""
        return SignatureVerifier()

    @pytest.fixture
    def key_pair(self):
        """Generate Ed25519 key pair for testing."""
        private_key = ed25519.Ed25519PrivateKey.generate()
        public_key = private_key.public_key()
        return private_key, public_key

    def test_verify_signature_success(self, verifier, key_pair):
        """Test successful signature verification."""
        private_key, public_key = key_pair
        data = b'test data'
        signature = private_key.sign(data)

        result = verifier.verify(data, signature, public_key)
        assert result is True

    def test_verify_signature_failure(self, verifier, key_pair):
        """Test signature verification failure."""
        private_key, public_key = key_pair
        data = b'test data'
        signature = private_key.sign(data)

        # Tamper with data
        tampered_data = b'tampered data'

        result = verifier.verify(tampered_data, signature, public_key)
        assert result is False

    def test_verify_signature_invalid_length(self, verifier, key_pair):
        """Test verification with invalid signature length."""
        _, public_key = key_pair
        data = b'test data'
        invalid_signature = b'short'

        result = verifier.verify(data, invalid_signature, public_key)
        assert result is False

    def test_verify_signature_from_hex(self, verifier, key_pair):
        """Test verification from hex-encoded signature."""
        private_key, public_key = key_pair
        data = b'test data'
        signature = private_key.sign(data)

        result = verifier.verify_from_hex(data, signature.hex(), public_key)
        assert result is True

    def test_sign_and_verify(self, verifier, key_pair):
        """Test signing and verifying data."""
        private_key, public_key = key_pair
        data = b'test data for signing'

        signature = verifier.sign(data, private_key)
        result = verifier.verify(data, signature, public_key)

        assert result is True


class TestManifestValidator:
    """Test suite for ManifestValidator class."""

    @pytest.fixture
    def validator(self):
        """Create a ManifestValidator instance."""
        return ManifestValidator()

    def test_validate_valid_manifest(self, validator):
        """Test validating a valid manifest."""
        manifest = RemoteManifest(
            version='2.0',
            metadata={'name': 'test', 'owner': 'test'},
            adapters=[],
            services=[],
            tasks=[],
            events=[],
            workflows=[]
        )

        result = validator.validate(manifest)
        assert result.is_valid is True

    def test_validate_missing_version(self, validator):
        """Test validating manifest without version."""
        manifest = {
            'metadata': {'name': 'test'},
            'adapters': []
        }

        with pytest.raises(ManifestError):
            validator.validate_dict(manifest)

    def test_validate_missing_metadata(self, validator):
        """Test validating manifest without metadata."""
        manifest = {
            'version': '2.0',
            'adapters': []
        }

        with pytest.raises(ManifestError):
            validator.validate_dict(manifest)

    def test_validate_invalid_adapter_entry(self, validator):
        """Test validating manifest with invalid adapter entry."""
        manifest = RemoteManifest(
            version='2.0',
            metadata={'name': 'test'},
            adapters=[
                ManifestEntry(
                    name='test',
                    # Missing required fields
                )
            ],
            services=[],
            tasks=[],
            events=[],
            workflows=[]
        )

        result = validator.validate(manifest)
        assert result.is_valid is False

    def test_validate_schema_version(self, validator):
        """Test schema version validation."""
        # Supported version
        manifest = RemoteManifest(
            version='2.0',
            metadata={'name': 'test'},
            adapters=[],
            services=[],
            tasks=[],
            events=[],
            workflows=[]
        )
        result = validator.validate(manifest)
        assert result.is_valid is True

        # Unsupported version
        invalid_manifest = RemoteManifest(
            version='999.0',
            metadata={'name': 'test'},
            adapters=[],
            services=[],
            tasks=[],
            events=[],
            workflows=[]
        )
        result = validator.validate(invalid_manifest)
        assert result.is_valid is False


class TestSecurityFunctions:
    """Test suite for security utility functions."""

    def test_compute_sha256(self):
        """Test SHA256 computation."""
        data = b'test data'
        hash_value = compute_sha256(data)

        assert hash_value is not None
        assert len(hash_value) == 64  # SHA256 produces 64 hex characters

    def test_compute_sha256_empty(self):
        """Test SHA256 computation for empty data."""
        data = b''
        hash_value = compute_sha256(data)

        assert hash_value is not None
        assert len(hash_value) == 64

    def test_compute_sha256_consistency(self):
        """Test SHA256 computation consistency."""
        data = b'consistent data'

        hash1 = compute_sha256(data)
        hash2 = compute_sha256(data)

        assert hash1 == hash2

    def test_verify_signature_function(self):
        """Test verify_signature utility function."""
        private_key = ed25519.Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        data = b'test data'
        signature = private_key.sign(data)

        result = verify_signature(data, signature, public_key)
        assert result is True

    def test_verify_signature_function_invalid(self):
        """Test verify_signature with invalid signature."""
        private_key = ed25519.Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        data = b'test data'
        signature = private_key.sign(data)

        # Tamper with data
        tampered_data = b'tampered'

        result = verify_signature(tampered_data, signature, public_key)
        assert result is False


class TestRemoteManifest:
    """Test suite for RemoteManifest class."""

    def test_manifest_creation(self):
        """Test creating RemoteManifest."""
        manifest = RemoteManifest(
            version='2.0',
            metadata={'name': 'test', 'owner': 'test_owner'},
            adapters=[],
            services=[],
            tasks=[],
            events=[],
            workflows=[]
        )

        assert manifest.version == '2.0'
        assert manifest.metadata['name'] == 'test'

    def test_manifest_from_dict(self):
        """Test creating RemoteManifest from dictionary."""
        manifest_dict = {
            'version': '2.0',
            'metadata': {'name': 'test'},
            'adapters': [],
            'services': [],
            'tasks': [],
            'events': [],
            'workflows': []
        }

        manifest = RemoteManifest(**manifest_dict)
        assert manifest.version == '2.0'

    def test_manifest_to_dict(self):
        """Test converting RemoteManifest to dictionary."""
        manifest = RemoteManifest(
            version='2.0',
            metadata={'name': 'test'},
            adapters=[],
            services=[],
            tasks=[],
            events=[],
            workflows=[]
        )

        manifest_dict = manifest.model_dump()
        assert manifest_dict['version'] == '2.0'

    def test_manifest_json_serialization(self):
        """Test JSON serialization of RemoteManifest."""
        manifest = RemoteManifest(
            version='2.0',
            metadata={'name': 'test'},
            adapters=[],
            services=[],
            tasks=[],
            events=[],
            workflows=[]
        )

        json_str = manifest.model_dump_json()
        assert '2.0' in json_str

        # Deserialize
        manifest2 = RemoteManifest.model_validate_json(json_str)
        assert manifest2.version == '2.0'


class TestManifestEntry:
    """Test suite for ManifestEntry class."""

    def test_entry_creation(self):
        """Test creating ManifestEntry."""
        entry = ManifestEntry(
            name='test_adapter',
            provider='redis',
            domain='cache',
            module_path='oneiric.adapters.cache.redis',
            version='1.0.0',
            priority=100
        )

        assert entry.name == 'test_adapter'
        assert entry.provider == 'redis'
        assert entry.domain == 'cache'

    def test_entry_with_signature(self):
        """Test ManifestEntry with signature."""
        entry = ManifestEntry(
            name='signed_adapter',
            provider='default',
            domain='test',
            module_path='test.module',
            signature='abc123',
            sha256='def456'
        )

        assert entry.signature == 'abc123'
        assert entry.sha256 == 'def456'

    def test_entry_with_capabilities(self):
        """Test ManifestEntry with capabilities."""
        entry = ManifestEntry(
            name='capable_adapter',
            provider='default',
            domain='test',
            module_path='test.module',
            capabilities=['feature1', 'feature2']
        )

        assert len(entry.capabilities) == 2
        assert 'feature1' in entry.capabilities

    def test_entry_validation(self):
        """Test ManifestEntry validation."""
        # Missing required field
        with pytest.raises(Exception):
            ManifestEntry(
                # name is missing
                provider='default',
                domain='test',
                module_path='test.module'
            )


class TestManifestError:
    """Test suite for ManifestError exception handling."""

    def test_manifest_error_creation(self):
        """Test creating ManifestError."""
        error = ManifestError(
            message='Test manifest error',
            manifest_path='/path/to/manifest.json'
        )

        assert 'Test manifest error' in str(error)
        assert error.manifest_path == '/path/to/manifest.json'

    def test_signature_error_creation(self):
        """Test creating SignatureError."""
        error = SignatureError(
            message='Invalid signature',
            manifest_path='/path/to/manifest.json'
        )

        assert 'Invalid signature' in str(error)

    def test_manifest_not_found_error(self):
        """Test ManifestNotFoundError."""
        error = ManifestNotFoundError(
            manifest_path='/nonexistent/manifest.json'
        )

        assert '/nonexistent/manifest.json' in str(error)
