# Importing Controls

When importing a profile or catalog for use in a Component Definition, SSP or other models as use cases arise.

Although implementation is incremental, all implementation must satisfy the NIST [OSCAL Profile Resolution](https://pages.nist.gov/OSCAL/learn/concepts/processing/profile-resolution/) specification.  

1. Build import tree
    - identify imports
    - ensure each import is reachable
    - cite blocked processing when an import is not found
        - receive alternative links to blocked imports

2. Enumerate control scope
    - import and organize group/control hierarchy:
        - ID: group or control ID {key}
            - label: group or control label
            - title: group or control title
            - status: if a status prop is present, include it here
            - source: the catalog that originally contained the control
            - included-by: array of profiles that imported the control
            - parameter-set-via: profiles that set the parameter constraint or value (via `set-parameters`)
            - modified-via: profiles that have alter the control (via `modify`)
            - cached_content: empty initially. populated when referenced.
            - children: a nested array of any child control or group
                - Groups can have child groups or child controls, but not both.
                - Controls can only have child controls.
    - for scope use `include`/`exclude` with
        - `all`/`by-id`/`matching`; adjusted by
            `with-child-controls`
        - scope-index: just IDs
    - for organization use 
        - `merge/flat`, `merge/as-is` or `merge/custom`
            - if a control is in scope it must be addressible and visible. 
                - With merge custom, any control not explicity addressed in organized into an "[Ungrouped]" group at the top.

3. Individual controls are loaded and processed only when the `get_control` method is used.
    - Lookup the control in the scope array
    - use the source to obtain the original content
    - use the parameter-set-via map to acquire parameter settings
    - use the modified-via map to acquire tailoring

`get_control(id: str, raw: boolean = False)`
- `id` is the control ID itself
- `raw`: If `True`, return the original source content and all tailoring as separate constructs
        If `False` (default) return only the final control after tailoring. 
