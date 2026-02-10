"""
Comprehensive configuration loader tests.

Tests configuration loading, validation, environment variable overrides,
and layer merging for Oneiric configuration system.
"""

import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest
import yaml
from pydantic import ValidationError

from oneiric.config import ConfigLoader, OneiricSettings


class TestConfigLoader:
    """Test suite for ConfigLoader class."""

    def test_load_yaml_config_success(self):
        """Test successful YAML configuration loading."""
        loader = ConfigLoader()

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as f:
            config_data = {
                'server_name': 'Test Server',
                'log_level': 'DEBUG',
                'profile': 'development'
            }
            yaml.dump(config_data, f)
            temp_path = f.name

        try:
            config = loader.load(temp_path)
            assert config is not None
            assert config['server_name'] == 'Test Server'
            assert config['log_level'] == 'DEBUG'
        finally:
            os.unlink(temp_path)

    def test_load_yaml_config_file_not_found(self):
        """Test loading non-existent YAML file."""
        loader = ConfigLoader()
        with pytest.raises(FileNotFoundError):
            loader.load('/nonexistent/path/config.yaml')

    def test_load_yaml_config_invalid_yaml(self):
        """Test loading invalid YAML file."""
        loader = ConfigLoader()

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as f:
            f.write("invalid: yaml: content:\n  - broken")
            temp_path = f.name

        try:
            with pytest.raises(yaml.YAMLError):
                loader.load(temp_path)
        finally:
            os.unlink(temp_path)

    def test_load_env_overrides(self):
        """Test environment variable overrides."""
        os.environ['ONEIRIC_SERVER_NAME'] = 'Override Server'
        os.environ['ONEIRIC_LOG_LEVEL'] = 'INFO'

        try:
            loader = ConfigLoader()
            config = loader.load_with_env_overrides()
            assert config.server_name == 'Override Server'
            assert config.log_level == 'INFO'
        finally:
            del os.environ['ONEIRIC_SERVER_NAME']
            del os.environ['ONEIRIC_LOG_LEVEL']

    def test_load_env_overrides_partial(self):
        """Test partial environment variable overrides."""
        os.environ['ONEIRIC_SERVER_NAME'] = 'Partial Override'

        try:
            loader = ConfigLoader()
            config = loader.load_with_env_overrides()
            assert config.server_name == 'Partial Override'
            # Other fields should use defaults
            assert config.log_level is not None
        finally:
            del os.environ['ONEIRIC_SERVER_NAME']

    def test_config_validation_success(self):
        """Test successful configuration validation."""
        loader = ConfigLoader()

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as f:
            config_data = {
                'server_name': 'Valid Config',
                'log_level': 'DEBUG',
                'profile': 'development'
            }
            yaml.dump(config_data, f)
            temp_path = f.name

        try:
            config = loader.load_and_validate(temp_path)
            assert config.server_name == 'Valid Config'
        finally:
            os.unlink(temp_path)

    def test_config_validation_invalid_log_level(self):
        """Test configuration validation with invalid log level."""
        loader = ConfigLoader()

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as f:
            config_data = {
                'server_name': 'Invalid Config',
                'log_level': 'INVALID_LEVEL'
            }
            yaml.dump(config_data, f)
            temp_path = f.name

        try:
            with pytest.raises(ValidationError):
                loader.load_and_validate(temp_path)
        finally:
            os.unlink(temp_path)

    def test_config_layered_loading(self):
        """Test layered configuration loading (defaults -> yaml -> env)."""
        loader = ConfigLoader()

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as f:
            config_data = {
                'server_name': 'YAML Config',
                'log_level': 'WARNING'
            }
            yaml.dump(config_data, f)
            temp_path = f.name

        os.environ['ONEIRIC_LOG_LEVEL'] = 'ERROR'

        try:
            config = loader.load_with_layering(temp_path)
            # YAML should provide server_name
            assert config.server_name == 'YAML Config'
            # Env should override log_level
            assert config.log_level == 'ERROR'
        finally:
            os.unlink(temp_path)
            del os.environ['ONEIRIC_LOG_LEVEL']

    def test_config_reload(self):
        """Test configuration reloading."""
        loader = ConfigLoader()

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as f:
            config_data = {'server_name': 'Original Config'}
            yaml.dump(config_data, f)
            temp_path = f.name

        try:
            config1 = loader.load(temp_path)
            assert config1['server_name'] == 'Original Config'

            # Modify file
            with open(temp_path, 'w') as f:
                yaml.dump({'server_name': 'Updated Config'}, f)

            config2 = loader.reload(temp_path)
            assert config2['server_name'] == 'Updated Config'
        finally:
            os.unlink(temp_path)

    def test_config_get_with_default(self):
        """Test getting configuration value with default."""
        loader = ConfigLoader()
        config = loader.load_with_env_overrides()

        # Test existing value
        assert config.get('server_name') is not None

        # Test non-existing value with default
        assert config.get('nonexistent_key', default='default_value') == 'default_value'

    def test_config_merge_dicts(self):
        """Test merging configuration dictionaries."""
        loader = ConfigLoader()

        dict1 = {'key1': 'value1', 'key2': 'value2'}
        dict2 = {'key2': 'updated_value2', 'key3': 'value3'}

        merged = loader.merge_dicts(dict1, dict2)
        assert merged['key1'] == 'value1'
        assert merged['key2'] == 'updated_value2'
        assert merged['key3'] == 'value3'

    def test_config_profile_specific_settings(self):
        """Test loading profile-specific configuration."""
        loader = ConfigLoader()

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as f:
            config_data = {
                'profile': 'production',
                'profiles': {
                    'production': {
                        'log_level': 'ERROR',
                        'debug': False
                    },
                    'development': {
                        'log_level': 'DEBUG',
                        'debug': True
                    }
                }
            }
            yaml.dump(config_data, f)
            temp_path = f.name

        try:
            config = loader.load_with_profile(temp_path)
            assert config.log_level == 'ERROR'
            assert config.debug is False
        finally:
            os.unlink(temp_path)

    def test_config_empty_file(self):
        """Test loading empty configuration file."""
        loader = ConfigLoader()

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as f:
            f.write("")
            temp_path = f.name

        try:
            # Should return empty dict or defaults
            config = loader.load(temp_path)
            assert isinstance(config, dict)
        finally:
            os.unlink(temp_path)

    def test_config_nested_values(self):
        """Test accessing nested configuration values."""
        loader = ConfigLoader()

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as f:
            config_data = {
                'server_name': 'Nested Test',
                'adapters': {
                    'cache': {
                        'provider': 'redis',
                        'config': {
                            'host': 'localhost',
                            'port': 6379
                        }
                    }
                }
            }
            yaml.dump(config_data, f)
            temp_path = f.name

        try:
            config = loader.load(temp_path)
            assert config['adapters']['cache']['provider'] == 'redis'
            assert config['adapters']['cache']['config']['port'] == 6379
        finally:
            os.unlink(temp_path)


class TestOneiricSettings:
    """Test suite for OneiricSettings Pydantic model."""

    def test_settings_default_values(self):
        """Test default values for OneiricSettings."""
        settings = OneiricSettings()
        assert settings.server_name is not None
        assert settings.log_level in ['DEBUG', 'INFO', 'WARNING', 'ERROR']
        assert settings.profile is not None

    def test_settings_custom_values(self):
        """Test custom values for OneiricSettings."""
        settings = OneiricSettings(
            server_name='Custom Server',
            log_level='DEBUG',
            profile='development'
        )
        assert settings.server_name == 'Custom Server'
        assert settings.log_level == 'DEBUG'
        assert settings.profile == 'development'

    def test_settings_validation_invalid_log_level(self):
        """Test OneiricSettings with invalid log level."""
        with pytest.raises(ValidationError):
            OneiricSettings(log_level='INVALID')

    def test_settings_from_dict(self):
        """Test creating OneiricSettings from dictionary."""
        config_dict = {
            'server_name': 'Dict Server',
            'log_level': 'WARNING'
        }
        settings = OneiricSettings(**config_dict)
        assert settings.server_name == 'Dict Server'
        assert settings.log_level == 'WARNING'

    def test_settings_to_dict(self):
        """Test converting OneiricSettings to dictionary."""
        settings = OneiricSettings(
            server_name='Export Server',
            log_level='INFO'
        )
        config_dict = settings.model_dump()
        assert config_dict['server_name'] == 'Export Server'
        assert config_dict['log_level'] == 'INFO'

    def test_settings_json_serialization(self):
        """Test JSON serialization of OneiricSettings."""
        settings = OneiricSettings(
            server_name='JSON Server',
            log_level='ERROR'
        )
        json_str = settings.model_dump_json()
        assert 'JSON Server' in json_str
        assert 'ERROR' in json_str

        # Deserialize
        settings2 = OneiricSettings.model_validate_json(json_str)
        assert settings2.server_name == 'JSON Server'
        assert settings2.log_level == 'ERROR'
