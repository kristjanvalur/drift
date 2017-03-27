# Drift Tutoral



Run the Redis server simply by executing `redis-server`.

To set up the PostgreSQL server, see [PostgreSQL setup](postgres-setup.md).

# We pick a location in our home directory
driftconfig create kdstudios file://~/kdstudios
driftconfig push kdstudios

# List out configuration DB's
driftconfig list
```

You can have multiple Drift configuration DB's active on your local workstation. To list them out, 


list out all DB's using the command `driftconfig list`. If there is **more than one** on your local machine, you need to explicitly point to it using a command line option, or add a reference to it through environment variable: `DRIFT_CONFIG_URL=file://~/.drift/config/kdstudios`.

### Set up a tier
A tier is a single slice of development or operation environment. It's a good practice to start with the live tier and if necessary add a dev and staging tier later, even though the live tier will only be used for development in the beginning.

For this tutorial however, we need a local development tier as well, so we will create one live and one local development tier:


### Register plugins and set up tiers

```bash
# Add a live tier and a local development tier
dconf tier add LIVE --is-live
dconf tier add LOCAL --is-dev

# Register all available Drift plugins in the config DB and associate
# with all available tiers
dconf deployable register all -t all


Now we have our LIVE tier set up, but all services need to run in the context of a product. Next step is to set up our organization and product.

```bash
# Arguments: organization name, short name, display name
dconf product add kd-snowfall
Drift is a multi-tenant platform. For our scenario we just need to create a tenant for our local development. Additional tenants can be created at any time as well.

Tenant names must be prefixed with the organization short name. Having the word 'default' in the name will make it the default tenant when running a service locally.

```bash
# Arguments: tenant name, product name
dconf tenant add kd-defaultdev kd-snowfall
```




```bash
drift-admin runserver drift-base
```

The server should be up and running on port 10080. To try it out:
```bash
curl -H accept:application/json http://localhost:10080
```

> Note: The 'drift-base' argument can be ommitted if cwd is in the repository of the project. Example: `➜  drift-base git:(develop) ✗ drift-admin runserver`

Using [Postman](https://www.getpostman.com/) for development is highly encouraged. There are other ways as well, but managing authorized sessions is best done using Postman and a set of helper scripts.

### What next
Next up is to set up the LIVE tier on AWS. Please follow the steps described in [Drift on AWS](drift-on-aws.md)

The final exercise is to create a new deployable/service. Please follow the steps described in [Drift Deployables](drift-deployables.md)


## Appendix (and scratch pad)

### AWS support
If you want AWS development and operation environment, make sure you have the AWS CLI suite installed, and access and secret keys set up on your local computer.

```bash
pip install awscli
aws configure

```


*(c) 2017 Directive Games North*