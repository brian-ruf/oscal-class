# ROADMAP

## Short Term

- XML vs JSON/YAML (tree vs dict) content handling:
    xx Analysis on trade-offs for one vs the other as authoritative.
    - tree/dict duality - native format determines which is primary
    - methods handle both, but only process the primary


- LOADING/SAVING CONTENT:
    - Finish save-to-file method for local files
    - Handle hrefs that point to local files, remote URLs, and file:// URIs
    - Handle hrefs that are URI fragments referencing back-matter/resources within the same file
    - For remote URLs, mark as read-only.

    - Classify the source based on its href and determine how to load it
    - Establish/verify basic "loading methods" based on source classification:
        - For local files, read directly from the file system
        - For file:// URIs, convert to local file path and read from the file system (same as local files, but need to handle the URI parsing and conversion)
        - For known but unsupported URI schemes, log a warning that we recognise the scheme but don't have a loading method for it yet

- IMPORTS:
    - Build an import tree that captures the structure of imports and their resolution status
    - Provide methods to retry failed imports with new hrefs
    - Implement properties to derive the effective state of the content based on its characteristics

- PROFILES:
    - Processes the import tree using above
    - instantiate catalog object within profile
        - Catalog is write-write for profile processing only
        - Profile methods that mimic the read-only catalog 
            - pass-through to the catalog object
            - Necessary tailoring and organization logic on top as needed
    - Resolve contol inclusion and organiztion for entire profile 
    - Handle control tailoring as controls are called
    - Method to resolve all control tailring at once after the full control set is assembled


## Medium Term

- LOADING/SAVING CONTENT:
    - For remote URLs
        - download the content and store it in a local cache directory
        - Local copy is read-only and has a TTL after which it is considered stale and needs to be re-fetched
        - configurable TTL (24 hour default) 
        - can be manually refreshed by calling code:
            - refetch from the remote URL and update the local cache copy, resetting the TTL
        - On loading, check if cached copy exists and is still valid (not expired). 
            - If so, load from cache. 
            - If not, fetch from remote URL and update cache.
        - Keep using cached copy after its TTL expires if the remote URL is not accessible, but mark the content as stale/expired so calling code can decide how to handle it (e.g. warn user, restrict editing, etc.)

- CONVERSION:
    - Shift from saxon/XSLT-based conversion to in-code conversion using Python libraries (e.g. xmltodict, dicttoxml, PyYAML)
        
- VALIDATION:
    - metaschema constraint evaluation always uses XML
        - If JSON is primary, convert to XML for MsC validation


## Long Term

- ADDRESSABLE ID SCOPE:
    - Handle hrefs that point to back-matter/resources within imported files (URI fragments)
    - Handle the ability to address IDs/UUIDs in imported files from an ancestor 

- LOADING/SAVING CONTENT:
- Konwon API Specifications:
    - OneDrive, Google Drive, S3, OSCAL API, etc. (Start with read-only OSCAL API)
    - Need ability to configure/store known API endpoints (Name, Base URL, Supported Operations, Authentication Method)
    - One fetch and one save method for each API, that handle the specifics of authentication, request formatting, response parsing, error handling, etc.
- Project approach to handling related OSCAL Files and their local attachments as a single, portable "project file store" that can be saved and loaded as a unit, with the ability to export/import individual files as needed.
    - !!! See Claude chat on project file stores.

