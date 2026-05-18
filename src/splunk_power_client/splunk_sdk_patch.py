from splunklib.client import (
    PATH_JOBS,
    PATH_JOBS_V2,
    Collection,
    Job,
    Jobs,
    Service,
    _parse_atom_metadata,
    record,
)

"""
This file contains patches to the Splunk SDK 

We add "published" and "author" attribute to the job object.
See: https://github.com/splunk/splunk-sdk-python/issues/619
"""


def _custom_parse_atom_entry(entry: dict) -> record:
    title = entry.get("title", None)

    elink = entry.get("link", [])
    elink = elink if isinstance(elink, list) else [elink]
    links = record((link.rel, link.href) for link in elink)

    # Retrieve entity content values
    content = entry.get("content", {})

    # Host entry metadata
    metadata = _parse_atom_metadata(content)

    # Filter some of the noise out of the content record
    content = record(
        (k, v) for k, v in content.items() if k not in ["eai:acl", "eai:attributes"]
    )

    if "type" in content:
        if isinstance(content["type"], list):
            content["type"] = [t for t in content["type"] if t != "text/xml"]
            # Unset type if it was only 'text/xml'
            if len(content["type"]) == 0:
                content.pop("type", None)
            # Flatten 1 element list
            if len(content["type"]) == 1:
                content["type"] = content["type"][0]
        else:
            content.pop("type", None)

    return record(
        {
            "title": title,
            "links": links,
            "access": metadata.access,
            "fields": metadata.fields,
            "published": entry.get("published"),
            "author": entry.get("author", {}).get("name"),
            "content": content,
            "updated": entry.get("updated"),
        }
    )


class JobFixed(Job):
    """This class represents a search job."""

    def __init__(self, service, sid, **kwargs):
        super().__init__(service, sid, **kwargs)

    # Load the entity state record from the given response
    def _load_state(self, response):
        entry = self._load_atom_entry(response)
        return _custom_parse_atom_entry(entry)


class JobsFixed(Jobs):
    def __init__(self, service):
        # Splunk 9 introduces the v2 endpoint
        if not service.disable_v2_api:
            path = PATH_JOBS_V2
        else:
            path = PATH_JOBS
        Collection.__init__(self, service, path, item=JobFixed)
        # The count value to say list all the contents of this
        # Collection is 0, not -1 as it is on most.
        self.null_count = 0


class NewService(Service):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @property
    def jobs(self):
        return JobsFixed(self)
