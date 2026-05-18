# Splunk URI Scheme

A custom URI scheme has been implemented to communicate with a Splunk instance easily and quickly. It's very similar to `scp` or `aws s3` commands.

For example, instead of write multiple arguments to specify a namespace for source and target instances, that could be annoying and lead to errors, you can just write something like this `s://my_instance/nobody/search/my_savedsearch_name`.

So, wherever you see the `RemotePath` annotation in a command's help, you'll need to use this custom URI scheme.

### Syntax

Basically, we have the scheme `s://` followed by the **INSTANCE** then the **PATH**, so:

- `s://<instance_name>/[user]/[app]/<resource_name>`
- `s://<token@host[:port]>/[user]/[app]/<resource_name>`
- `s://<user[:password]@host[:port]>/[user]/[app]/<resource_name>`

/// admonition | Host Specification
The `token` keyword must be explicitly specified in order to be requested at the prompt otherwise, the word will be considered as a username.
///

If no **PATH** segment is given for

- the source, will consider the given element as an object and if it not found, SPC will raise `ResourceNotFound`.
    - if so, check your namespace, it's a frequent mistake.
- the target, the source object name will be used with the default target instance namespace.
    - tip: you can use the `--use-source-namespace` option to set the same namespace as the source

If **PATH** is given, it will be parsed in the order specified, i.e. `user / app / resource`. But user and app value is not mandatory.

For example, you want to change only the target app, so you just need to add a valueless slash to pass the user value, for example: `s://dev//my_app/my_resource` _(note the double slash)_


### Wildcard support

> This applies only to `lookups` and `savedsearches` commands.

`<resource_name>` segment support wildcard `*` for `SOURCE` argument.

For Lookup Local files, `Path.glob()` will be invoked to detects the list of files to handles.

For Remote Resources, an API call will be executed to filter the resources to be used.

### Examples

```sh
# push 'dummy_alerts_samples.csv' to Dev Splunk instance
spc lookups cp dummy_alerts_samples.csv s://dev

# same but you want to rename the destination file
spc lookups cp dummy_alerts_samples.csv s://dev/alerts_samples.csv

# you want to copy the lookup into another app
# see the double slash in the PATH
spc lookups cp dummy_alerts_samples.csv s://dev//my_app

# set user to 'nobody' and change the final destination file name
spc lookups cp dummy_alerts_samples.csv s://dev/nobody/my_app/alerts.csv

# push all csv files from current directory into Dev Splunk instance
# note: you need to escape wildcard from your shell
spc lookups cp '*.csv' s://dev

# or sync some lookups from Production instance to Dev instance
spc lookups cp --use-source-namespace 's://prod//my_app/*' s://dev//my_app
```
