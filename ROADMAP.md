# ROADMAP (_Updated Apl 26, 2026_)

The sequencing of releases may change in response to client needs and other external factors.

## Past: 

### Version 1.x

- Support Module: Acquire and manage NIST-pubished support files
    - Support files in local SQLite database
    - Support files in local Folder
    - Deploy, update, and repopulate
- OSCAL Content Class: 
    - Simple local loading and saving
    - Auto-detect OSCAL format, version and model
    - Validation using NIST schema files
    - Load any OSCAL format (XML, JSON, YAML)
    - Convert and save in any OSCAL format (XML, JSON, YAML)
        - Currently relies on SaxonC-HE and NIST XSLT 3.x Convertion files

## Current: 

### Version 2.0.x: Refactoring, XML/JSON Parity

- Separate class for each model
- Refactor class attributes, methods (names, organization)
- Efficiency and maintainability improvements
- Robust Loading from local file system and remote URLs

## Next

### Importing Dependency Chain

- [ ] Top level imports 
    - AR -> AP -> SSP -> Profile -> [ Profile | Catalog ]
    - POAM -> SSP -> Profile -> [ Profile | Catalog ]
    - cDef -> cDef
- [ ] Failed import handling
- [ ] Basic addressibility across imported files

### Profile Resolution

- [ ] Control Tree Generation/Caching
- [ ] By-Control Tailoring
- [ ] Saving Resolved Profile Catalogs

### Local Caching

- [ ] Cache remotely acquired files locally
- [ ] Automatic cache refresh based on TTL
- [ ] Manually triggered refresh
- [ ] Fallback to cache after expiration when remote content is not available.

### Project Approach

- [ ] Project-based Storage
    - Save cluster of related files together
        - AR -> AP -> SSP -> Profile -> [ Profile | Catalog ]
        - POAM -> SSP -> Profile -> [ Profile | Catalog ]
    - SQLite-based
    - Load cluster of related files
    - External attachment packing with project

- [ ] External attachment handling    
    - In SQLite project file
    - As external files relative to SQLite project file

### Indexes and Robust Addressibility

- [ ] Generate and maintain metaschema-defined indexes
- [ ] Generate and maintain extra-metaschema indexes 
- [ ] Handle metaschema-defined uniqueness constraints
- [ ] Enable robust addressibility across project files
  - Easily search for ID/UUID referencess across a project, consistent with OSCAL addressibility scope and requirements


### Farther Out


- [ ] Robust URI and APIs Handling for Content Acquisition/Storage
    - Additional API Specifications
    - Credentialed/Access-token Handling
    - S3 and similar cloud-native storage capabiities 

- [ ] Content Library
    - Cached local copy of commonly used OSCAL content, such as the NIST SP 800-53 catalog and FedRAMP profiles.
    - Ability to add/refresh/remove content

- [ ] Preferred Conversion
    - Enable conversion of OSCAL content using pure python and direct interpretation of metaschema
        - Eliminates dependency on XSLT 3.x processing for format converstion

- [ ] Preferred Validation
    - Enable validation of OSCAL content using pure Python and direct interpretation of NIST metaschema 
        - Eliminate dependency on XML/JSON schema files
        - Enables more complex metaschema checks 

- [ ] Project Storage and Sharing Enhancements
    - Enable multi-user interaction of shared project files
    - Enable storage on shared network drives
    - Enable storage on shared cloud drives (OneDrive, Google Drive)
    - Enablue use of enterprise databases


