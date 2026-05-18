# Jobs

Add API Reference

## Examples

- order by app
  - 'eai:acl.app="search"'
- order by author
  - 'eai:acl.owner="admin"' ou 'user=""'
- order by diskUsage
- order by runDuration

pour exporter au format raw, il faut avoir la clé \_raw dans la recherche
donc soit y'a pas d'agrégation (stats, tstats, table etc)
soit le champs \_raw est retourné

export - .csv - .json - .xslx - .txt/.log -> raw
