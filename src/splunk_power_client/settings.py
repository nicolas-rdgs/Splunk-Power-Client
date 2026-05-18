from typing import Any, Optional, Tuple, Type

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    InitSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from pydantic_settings.sources import ConfigFileSourceMixin

from .models import SplunkInstance
from .utils import Path, get_default_instance_name, spc_config_file, spc_dotenv_file


class SPCTomlConfigSettingsSource(InitSettingsSource, ConfigFileSourceMixin):
    """
    A custom source class to handle SPC Splunk instances from Toml configuration file.

    Try to load a Splunk instance and fill it with default values if necessary
    Otherwise, a null dict is returned to search values in environment variables
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        toml_file: Path | None,
        init_settings: InitSettingsSource,
    ) -> None:
        self.settings_cls = settings_cls
        self.toml_file_path = toml_file
        instance_name: Optional[str] = init_settings.init_kwargs.get("name")

        self.toml_data = self._read_files(self.toml_file_path)
        if instance_name is None:
            instance_name = get_default_instance_name(self.toml_data)

        self.config_data = {
            "name": instance_name,
            "exists": False,
            "instance": {"name": instance_name},
        }

        self.toml_data = self.toml_data.get(instance_name, {})

        if "host" in self.toml_data and "port" in self.toml_data:
            self.config_data["exists"] = True
            self.get_field_value()
        elif instance_name:
            self.get_field_value()

        super().__init__(settings_cls, self.config_data)

    def _read_file(self, file_path: Path) -> dict[str, Any]:
        import tomllib

        with file_path.open("rb") as toml_file:
            return tomllib.load(toml_file)

    def get_field_value(self) -> None:
        instance_model = dict(self.settings_cls.model_fields["instance"].default)
        for field_name, field_value in instance_model.items():
            if field_name == "name":
                continue
            self.config_data["instance"][field_name] = self.toml_data.get(
                field_name, field_value or None
            )


class Settings(BaseSettings):
    """Load a SPC Splunk Instance

    ### Arguments
    - *name: str (default: _None_)
      - Name of the instance to load, if not specified, try to load the default one

    ### Returns:
    - A Pydantic Settings class
    """

    name: Optional[str] = Field(None, description="Name of SPC Instance")
    exists: bool = Field(False, description="Define if the instance already exists")
    instance: SplunkInstance = SplunkInstance()

    model_config = SettingsConfigDict(
        env_file=spc_dotenv_file,
        env_prefix="spc_",
        env_nested_delimiter="__",
        nested_model_default_partial_update=True,
        # extra="allow",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            SPCTomlConfigSettingsSource(
                settings_cls=settings_cls,
                toml_file=spc_config_file,
                init_settings=init_settings,
            ),
            DotEnvSettingsSource(settings_cls),
            env_settings,
        )
