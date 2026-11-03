# Lookups

This command lets you quickly:

- copy lookups from local to Splunk, Splunk to local or Splunk to Splunk
- push lookups toward multiple instances
- list lookups of an instance
- delete specific lookup or multiples
- create a KVStore collection with its lookup definition

specifier que "rm" pour les kv, supprime uniquement les données pas le kvstore avec la conf

## URI specific

As described in [SPC URI Scheme](../splunk_uri_scheme.md), the `resource` part of the PATH, must be a **lookup name**.

## Local file format

a déplacer dans une page plus global, LocalLookup est utilisé dans plusieurs commandes

### CSV

.

### Excel

..

### JSON

...

## Splunk API Reference

https://docs.splunk.com/Documentation/Splunk/9.4.2/RESTREF/RESTkvstore#storage.2Fcollections.2Fdata.2F.7Bcollection.7D

## CSV Fields size limit

In most cases, the `csv` library returns a default value of 128 KB for parsing columns. If you have a csv with many columns, you need to increase this value by specifying the `--csv-field-size-limit` option.

## Examples

```sh
# push 'dummy_alerts_samples.csv' to Dev Splunk instance (it will use default namespace)
spc lookups cp dummy_alerts_samples.csv s://dev

# same but you want to rename the destination file
spc lookups cp dummy_alerts_samples.csv s://dev/alerts_samples.csv

# you want to copy the lookup into another app
# see the double slash for the PATH
spc lookups cp dummy_alerts_samples.csv s://dev//my_app

# set user to 'nobody' and change the final destination file name
spc lookups cp dummy_alerts_samples.csv s://dev/nobody/my_app/alerts.csv

# push all csv files from current directory into Dev Splunk instance
# note: you need to escape wildcard from your shell, the spc doesn't support shell expansion because of Typer limitations.
spc lookups cp '*.csv' s://dev

# or sync some lookups from Production instance to Dev instance
spc lookups cp 's://prod//my_app/*' s://dev//my_app
```

## Create a KVStore collection

`spc lookups mkkv <RemotePath>` creates the collection (`storage/collections/config`) and, by default, a lookup definition with the same name (`transforms.conf`, `external_type = kvstore`) so it can be used straight away with `| inputlookup` / `| outputlookup`.

- `--field / -f NAME[:TYPE]` — repeatable, `TYPE` is one of `string` (default), `number`, `bool`, `time`, `array`.
- `--from-file PATH` — use the columns of a local CSV / JSON / Excel file as `string` fields. Can be combined with `--field` to override a type.
- `--accelerated-field NAME=FIELD1,FIELD2` — repeatable, creates an acceleration (index) on the given fields.
- `--enforce-types`, `--replicate` — collection options, both disabled by default.
- `--no-definition` / `--definition-name NAME` — skip or rename the lookup definition.

/// admonition | Namespace
    type: tip

KVStore collections are app-level objects: use `nobody` as owner, e.g. `s://dev/nobody/my_app/my_collection`.
///

```sh
# create a collection with typed fields and an acceleration
spc lookups mkkv s://dev/nobody/my_app/assets -f host -f ip -f last_seen:time --accelerated-field by_host=host

# infer the schema from a local file, then load it
spc lookups mkkv s://dev//my_app/assets --from-file assets.csv
spc lookups cp assets.csv s://dev//my_app/assets --target-kv
```

## KVStore as code (YAML templates)

Declare a collection (`collections.conf`) and its lookup definition (`transforms.conf`) once in YAML, then apply them to any instance. Templates are validated with pydantic against the Splunk 10.0 specs (unknown keys and invalid values are refused) and translated into REST calls.

```
~/.spc/templates/             # or --templates-dir / SPC_TEMPLATES_DIR (e.g. a git repo)
├── collections/assets.yaml
└── definitions/assets.yaml
```

Annotated templates listing every key and allowed value: [`examples/kvstore/collections/_template.yaml`](https://github.com/nicolas-rdgs/Splunk-Power-Client/blob/main/examples/kvstore/collections/_template.yaml) and [`examples/kvstore/definitions/_template.yaml`](https://github.com/nicolas-rdgs/Splunk-Power-Client/blob/main/examples/kvstore/definitions/_template.yaml).

```sh
# show what would change, nothing is written
spc lookups mkkv s://dev//my_app -c assets -d assets --dry-run

# create or update (idempotent): same command after editing the YAML
spc lookups mkkv s://dev//my_app -c assets -d assets
spc lookups mkkv s://prod//my_app -c assets -d assets
```

- `-c` / `-d` take a template name (resolved in `collections/` / `definitions/`) or a path to a `.yaml` file.
- Only the changed keys are sent on update. Keys present on Splunk but absent from the template (fields, accelerations) are reported as `drift (kept)` and never removed.
- `sharing` in a template is applied through the object ACL, keeping its current owner.
- With `-d` alone, a collection template with the same name is used, if present, for `fields_list` and consistency checks.

/// admonition | Search head cluster
    type: tip

Apply on any member: configuration replication propagates the objects to the other members.
///
