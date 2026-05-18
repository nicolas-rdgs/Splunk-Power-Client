# Lookups

This command lets you quickly:

- copy lookups from local to Splunk, Splunk to local or Splunk to Splunk
- push lookups toward multiple instances
- list lookups of an instance
- delete specific lookup or multiples

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
