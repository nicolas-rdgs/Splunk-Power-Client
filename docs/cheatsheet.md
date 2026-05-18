# Use Cases CheatSheet

Assemble in one page all commands that fit a specific and well-known needs!

## Lookups

- Create a KvStore and push data from JSON file

```sh
spc configs set ...
spc lookups cp data.json s://myInstance
```

## Jobs

## Configs

## Saved Searches

- Delete saved searches that starts with `AAA` on `Rules` Splunk App:

`spc searches rm --search "eai:acl.app=rules name=AAA*" --force`
