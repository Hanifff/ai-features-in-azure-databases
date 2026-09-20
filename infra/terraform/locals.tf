locals {
  prefix = var.name_prefix

  names = {
    resource_group = coalesce(var.resource_group_name, "rg-${local.prefix}-${var.location}-001")
    postgres       = "psql-${local.prefix}-${var.location}-001"
    cosmos         = "cosmos-${local.prefix}-${var.location}-001"
    foundry        = "aif-${local.prefix}-${var.location}-001"
  }

  # Grant the identity running Terraform unless told otherwise, so a first-time
  # apply leaves a working environment with no second step.
  admin_object_ids = length(var.admin_object_ids) > 0 ? var.admin_object_ids : [data.azurerm_client_config.current.object_id]

  # Cosmos data-plane built-in role. Control-plane RBAC grants no data access,
  # which is the usual reason a subscription Owner still gets 403 from the SDK.
  cosmos_data_contributor_role_id = "00000000-0000-0000-0000-000000000002"

  postgres_extensions = "vector,pg_diskann,azure_ai,age"

  # age needs this in addition to the allow-list. The value replaces rather than
  # appends, so defaults worth keeping are listed explicitly. Changing it
  # restarts the server.
  postgres_shared_preload_libraries = "age,pg_stat_statements"

  firewall_ranges = var.allow_all_networks ? {
    "allow-all" = { start = "0.0.0.0", end = "255.255.255.255" }
    } : {
    for idx, cidr in var.allowed_ip_rules :
    format("allowed-%02d", idx) => {
      start = cidrhost(cidr, 0)
      end   = cidrhost(cidr, pow(2, 32 - tonumber(split("/", cidr)[1])) - 1)
    }
  }

  # Cosmos treats an empty filter as allow-all, rejects 0.0.0.0/0 outright, and
  # reads a bare "0.0.0.0" as "accept Azure datacentres" rather than as an
  # address. So allow-all has to be expressed as no rules at all.
  cosmos_ip_filter = var.allow_all_networks || length(var.allowed_ip_rules) == 0 ? [] : toset(concat(
    var.allowed_ip_rules,
    var.allow_azure_services ? ["0.0.0.0"] : [],
  ))
}
