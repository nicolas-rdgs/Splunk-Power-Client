
If there is no behavior that fit your goals, you need to write script and you can use Settings to load and login your instance instead of rewrite basics.

Example:

```py
from splunk_power_client.settings import Settings

ins_settings = Settings(name="dev")
ins_settings.instance.login()

ins_settings.instance.service
```
