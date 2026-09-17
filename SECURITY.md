# Security

This repository contains **sample code written for a conference demonstration**.
It is not a product, it is not supported, and it is not intended for production
use. Please read the warnings in the README before reusing any of it.

## Reporting a problem in this sample

Open a GitHub issue. If the problem is something you would rather not describe in
public, say so in the issue without detail and a private channel will be arranged.

## Reporting a vulnerability in an Azure service

If you believe you have found a security vulnerability in **Microsoft software or
an Azure service**, rather than in this sample, do not report it here.

Report it to the Microsoft Security Response Center at
<https://msrc.microsoft.com/create-report>, or email <secure@microsoft.com>.
More detail at <https://www.microsoft.com/msrc>.

## Known, deliberate weaknesses in this sample

These are called out so nobody has to discover them by reading the Terraform:

- Both databases accept connections from any network. The demo is driven from
  several networks that cannot be predicted in advance.
- Both databases use public endpoints rather than private endpoints.
- The dataset is synthetic. There is no real, customer or personal data in it.

Authentication is Entra-only throughout, with key and password authentication
disabled, so network exposure alone grants nothing. That is what makes the above
acceptable for a short-lived demo environment, and it is still the wrong shape
for production.
