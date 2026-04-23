## The OSCAL Support Module

The `OSCAL_Support` class creates and maintains a database that contains all of the NIST-published support files for all OSCAL versions and models. This is referred to in documentation as the _OSCAL Support Module_.

The `OSCAL` class is able to validate and convert any OSCAL version and module where the NIST-published support files are present in the _OSCAL Support Model_. No Internet connection required.

As NIST publishes additional modules, they can be added to the OSCAL Support Module. An Internet connect is rquired to update the OSCAL Support Module; however, once updated, it can be copied to any computer for use.

### Designed for Air Gapped Environments

The concept behind the _OSCAL Support Module_ is that it can be generated or updated on an Internet-connected computer and then conveyed into an air gapped environment for use. When updated, it enables support for all published OSCAL formats, versions, and models.   

### Open Standard

The OSCAL Support Module is a SQLite 3 database, implemented without encryption so that tables can be inspected. Each cached file is stored as a blob. 

The default configuration is to compress each cached file before storing; however, the compression can be turned off for even greater transparency with the trade-off of increased file size. 

This default name and location for the OSCAl Support Module is `./support/oscal_support.db`; however, your project code can override the location and/or the file name. 

To change the location or type of database, issue the following command before instantiating any OSCAL objects or calling `get_support`.

```python

configure_support(support_file="/path/support.db", db_init_mode="auto")

```

If the database file is not found, it is created. This library contains all 
NIST-published support files for all versions of OSCAL available as of this
library's published date.

To update the support database directly from the NIST OSCAL GitHub repo, execute the following:

```python

support = get_support()

# Check for a new version of OSCAL. If found, add its support files to the database.
support.update()
# or
support.update(fetch="new")    

# Clear the database and re-acquire the support files for all versions of OSCAL.
support.update(fetch="all") 

# Refresh the support files for a specific version of OSCAL.
support.update(fetch="v1.0.0") 

```

The `OSCAL_support` class interacts with the SQLite3 database using ANSI SQL with the intention of expanding support for project and enterprise ANSI SQL databases in the future, such as Postgres, MS SQL Server, and Oracle.
