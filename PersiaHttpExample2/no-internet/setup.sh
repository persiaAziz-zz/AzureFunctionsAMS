#!/bin/bash
set -e

az extension add -n sap-hana 2>/dev/null
az extension add -n log-analytics 2>/dev/null

SAPMON_RG=$1
SAPMON_NAME=$2

SAPMON=$(az sapmonitor show -g ${SAPMON_RG} -n ${SAPMON_NAME})
if [ $? -ne 0 ]; then
    echo "Unable to find SapMonitor"
    exit 1
fi

echo ${SAPMON} | jq

SUBSCRIPTION_ID=$(echo ${SAPMON} | jq .id -r | cut -d'/' -f3)
SAPMON_ID=$(echo ${SAPMON} | jq .managedResourceGroupName -r | cut -d'-' -f3)
COLLECTOR_VERSION=$(echo ${SAPMON} | jq .sapMonitorCollectorVersion -r)
MONITOR_SUBNET=$(echo ${SAPMON} | jq .monitorSubnet -r)
VNET_RG=$(echo ${MONITOR_SUBNET} | cut -d'/' -f5)
VNET_NAME=$(echo ${MONITOR_SUBNET} | cut -d'/' -f9)
SUBNET_NAME=$(echo ${MONITOR_SUBNET} | cut -d'/' -f11)
LAWS_ARM_ID=$(echo ${SAPMON} | jq .logAnalyticsWorkspaceArmId -r)
LAWS_SUBSCRIPTION=$(echo ${LAWS_ARM_ID} | cut -d'/' -f3)
LAWS_RG=$(echo ${LAWS_ARM_ID} | cut -d'/' -f5)
LAWS_NAME=$(echo ${LAWS_ARM_ID} | cut -d'/' -f9)

UNSUPPORTED_VERSIONS=("" "v1.5" "v1.6" "v2.0-beta" "2.0" "2.1" "2.2")

if [[ " ${UNSUPPORTED_VERSIONS[@]} " =~ " ${COLLECTOR_VERSION} " ]]; then
    echo "The SapMonitor is of an unsupported version, please recreate the SapMonitor"
    exit 1
fi

while true; do
    read -p "Is this the SapMonitor you want to update? (y/n): " yn
    case $yn in
        [Yy]* ) break;;
        [Nn]* ) exit;;
        * ) echo "Please answer yes or no.";;
    esac
done

echo "==== Fetching Log-Analytics information ===="
WORKSPACE_ID=$(az monitor log-analytics workspace show \
    --subscription ${LAWS_SUBSCRIPTION} \
    --resource-group ${LAWS_RG} \
    --workspace-name ${LAWS_NAME} \
    --query "customerId" \
    --output tsv)
SHARED_KEY=$(az monitor log-analytics workspace get-shared-keys \
    --subscription ${LAWS_SUBSCRIPTION} \
    --resource-group ${LAWS_RG} \
    --workspace-name ${LAWS_NAME} \
    --query "primarySharedKey" \
    --output tsv)

echo "==== Uploading Storage Account key to KeyVault ===="
USER_PRINCIPAL_NAME=$(az ad signed-in-user show --query "userPrincipalName" --output tsv)
STORAGE_KEY=$(az storage account keys list -n sapmonsto${SAPMON_ID} --query [0].value -o tsv)
az keyvault set-policy \
    --name sapmon-kv-${SAPMON_ID} \
    --resource-group sapmon-rg-${SAPMON_ID} \
    --upn ${USER_PRINCIPAL_NAME} \
    --secret-permissions set \
    --output none
az keyvault secret set \
    --vault-name sapmon-kv-${SAPMON_ID} \
    --name storageAccessKey \
    --value ${STORAGE_KEY} \
    --output none
az keyvault delete-policy \
    --name sapmon-kv-${SAPMON_ID} \
    --resource-group sapmon-rg-${SAPMON_ID} \
    --upn ${USER_PRINCIPAL_NAME} \
    --output none

echo "==== Downloading installation files ===="
wget -O no-internet-install-${COLLECTOR_VERSION}.tar https://github.com/Azure/AzureMonitorForSAPSolutions/releases/download/${COLLECTOR_VERSION}/no-internet-install-${COLLECTOR_VERSION}.tar

echo "==== Uploading installation files to Storage Account ===="
az storage container create \
    --account-name sapmonsto${SAPMON_ID} \
    --name no-internet \
    --public-access blob \
    --output none 2>/dev/null
az storage blob upload \
    --account-name sapmonsto${SAPMON_ID} \
    --container-name no-internet \
    --name no-internet-install-${COLLECTOR_VERSION}.tar \
    --file no-internet-install-${COLLECTOR_VERSION}.tar \
    --output none 2>/dev/null

echo "==== Upgrading Storage Acocunt from v1 to v2 ===="
az storage account update \
    -g sapmon-rg-${SAPMON_ID} \
    -n sapmonsto${SAPMON_ID} \
    --set kind=StorageV2 \
    --access-tier=Hot \
    --output none

echo "==== Disable private endpoint policies on NSG ===="
az network vnet subnet update \
    --name ${SUBNET_NAME} \
    --resource-group ${VNET_RG} \
    --vnet-name ${VNET_NAME} \
    --disable-private-endpoint-network-policies true \
    --output none

# Creating private endpoint on Storage Blob, Queue, and Key Vault
createPrivateEndpoint() {
    endpoint_name=$1
    type=$2
    connection_resource_id=$3
    private_dns_zone_name=$4

    echo "==== Creating Private Endpoint ${endpoint_name} ===="
    zone_name=$(echo $private_dns_zone_name | sed 's/\./-/g')
    az network private-endpoint create \
        --name ${endpoint_name} \
        --resource-group sapmon-rg-${SAPMON_ID} \
        --subnet ${MONITOR_SUBNET} \
        --private-connection-resource-id ${connection_resource_id} \
        --group-id ${type} \
        --connection-name ${endpoint_name} \
        --output none

    echo "==== Creating Private DNS Zone ${private_dns_zone_name} ===="
    set +e
    az network private-dns zone show \
        --resource-group ${VNET_RG} \
        --name ${private_dns_zone_name} \
        --output none 2>/dev/null
    status=$?
    set -e
    if [ $status -ne 0 ]; then
        az network private-dns zone create \
          --resource-group ${VNET_RG} \
          --name ${private_dns_zone_name} \
          --output none
    else
        echo "Private DNS zone already exists, skip creation"
    fi

    echo "==== Linking Private DNS with VNet ===="
    set +e
    az network private-dns link vnet show \
        --resource-group ${VNET_RG} \
        --zone-name ${private_dns_zone_name} \
        --name ${type}-${SAPMON_ID} \
        --output none 2>/dev/null
    status=$?
    set -e
    if [ $status -ne 0 ]; then
        az network private-dns link vnet create \
          --resource-group ${VNET_RG} \
          --zone-name ${private_dns_zone_name} \
          --name ${type}-${SAPMON_ID} \
          --virtual-network ${VNET_NAME} \
          --registration-enabled false \
          --output none
    else
        echo "Private DNS already linked with VNet, skip linking"
    fi

    echo "==== Creating Private DNS entry for the Private Endpoint ===="
    az network private-endpoint dns-zone-group create \
        --resource-group sapmon-rg-${SAPMON_ID} \
        --endpoint-name ${endpoint_name} \
        --name default \
        --private-dns-zone /subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${VNET_RG}/providers/Microsoft.Network/privateDnsZones/${private_dns_zone_name} \
        --zone-name ${zone_name} \
        --output none
}
createPrivateEndpoint PrivateEndpointStorageBlob blob /subscriptions/${SUBSCRIPTION_ID}/resourceGroups/sapmon-rg-${SAPMON_ID}/providers/Microsoft.Storage/storageAccounts/sapmonsto${SAPMON_ID} privatelink.blob.core.windows.net
createPrivateEndpoint PrivateEndpointStorageQueue queue /subscriptions/${SUBSCRIPTION_ID}/resourceGroups/sapmon-rg-${SAPMON_ID}/providers/Microsoft.Storage/storageAccounts/sapmonsto${SAPMON_ID} privatelink.queue.core.windows.net
createPrivateEndpoint PrivateEndpointKeyVault vault /subscriptions/${SUBSCRIPTION_ID}/resourceGroups/sapmon-rg-${SAPMON_ID}/providers/Microsoft.KeyVault/vaults/sapmon-kv-${SAPMON_ID} privatelink.vaultcore.azure.net

echo "==== Creating Private Link Scope for Log-Analytics ===="
az monitor private-link-scope create \
    --name PrivateLinkScopeLAWS \
    --resource-group sapmon-rg-${SAPMON_ID} \
    --output none
az monitor private-link-scope scoped-resource create \
    --linked-resource ${LAWS_ARM_ID} \
    --name ${LAWS_NAME} \
    --resource-group sapmon-rg-${SAPMON_ID} \
    --scope-name PrivateLinkScopeLAWS \
    --output none
createPrivateEndpoint PrivateEndpointLAWS azuremonitor /subscriptions/${SUBSCRIPTION_ID}/resourceGroups/sapmon-rg-${SAPMON_ID}/providers/microsoft.insights/privateLinkScopes/PrivateLinkScopeLAWS privatelink.ods.opinsights.azure.com


echo "==== Configuring Collector VM ===="
COMMAND_TO_EXECUTE="wget https://sapmonsto${SAPMON_ID}.blob.core.windows.net/no-internet/no-internet-install-${COLLECTOR_VERSION}.tar && \
tar -xf no-internet-install-${COLLECTOR_VERSION}.tar && \
dpkg -i "'$(tar -tf no-internet-install-'"${COLLECTOR_VERSION}"'.tar | grep containerd.io_)'" && \
dpkg -i "'$(tar -tf no-internet-install-'"${COLLECTOR_VERSION}"'.tar | grep docker-ce-cli_)'" && \
dpkg -i "'$(tar -tf no-internet-install-'"${COLLECTOR_VERSION}"'.tar | grep docker-ce_)'" && \
docker load -i azure-monitor-for-sap-solutions-${COLLECTOR_VERSION}.tar && \
docker run mcr.microsoft.com/oss/azure/azure-monitor-for-sap-solutions:${COLLECTOR_VERSION} python3 /var/opt/microsoft/sapmon/${COLLECTOR_VERSION}/sapmon/payload/sapmon.py onboard --logAnalyticsWorkspaceId ${WORKSPACE_ID} --logAnalyticsSharedKey ${SHARED_KEY} --enableCustomerAnalytics > /tmp/monitor.log.out && \
mkdir -p /var/opt/microsoft/sapmon/state && \
docker run --name sapmon-ver-${COLLECTOR_VERSION} --detach --restart always --network host --volume /var/opt/microsoft/sapmon/state:/var/opt/microsoft/sapmon/${COLLECTOR_VERSION}/sapmon/state --env Version=${COLLECTOR_VERSION} mcr.microsoft.com/oss/azure/azure-monitor-for-sap-solutions:${COLLECTOR_VERSION} sh /var/opt/microsoft/sapmon/${COLLECTOR_VERSION}/monitorapp.sh ${COLLECTOR_VERSION}"

az vm extension set \
    --resource-group sapmon-rg-${SAPMON_ID} \
    --vm-name sapmon-vm-${SAPMON_ID} \
    --name customScript \
    --publisher Microsoft.Azure.Extensions \
    --protected-settings "{\"commandToExecute\": \"${COMMAND_TO_EXECUTE}\"}" \
    --output none

echo "==== Update Complete ===="
