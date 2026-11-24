---
title: "Terms of use"
description: "The terms for using the PHAEMOS website and the hosted PHAEMOS service."
version: "[PUBLICATION DATE]"
versionLabel: "Version date"
---

These terms cover the PHAEMOS website{if hosted: and the hosted PHAEMOS service}. {if not hosted:The hosted service is not open yet. These terms will cover it once it opens. }Please read them before you use {if hosted:either}{if not hosted:the website}.

## 1. Who we are and what these terms cover

PHAEMOS is run by Isaac Adjei as an individual{if hosted: of [POSTAL ADDRESS OF THE CONTROLLER]}. There is no company behind it. In these terms "we" means Isaac Adjei. You can reach us at [contact@phaemos.com](mailto:contact@phaemos.com).

These terms cover:

- the website at {site} and the documentation at docs.phaemos.com (the "website")
- the dashboard at {app} and the API at {api} that we run for people we have invited (the "hosted service"). {if hosted}
- the dashboard and the API that we will run for people we invite once it opens (the "hosted service"). {if not hosted}

{if hosted:By creating an account you agree to these terms. } If you only browse the website, sections 5, 6, 9, 11, 13 and 15 to 17 are the ones that apply to you.

These terms do not cover a copy of PHAEMOS that you or anyone else runs. Section 6 explains how the open source licences fit in.

## 2. The service and where it stands today

PHAEMOS collects readings from sensor nodes attached to machines, stores them, scores them with a machine learning model, raises alerts and tracks the maintenance tickets that follow.

:::if hosted
The software works from end to end but the project is at an early stage. The sensor hardware is designed and not yet built. Until it is installed, the readings in the hosted service come from a simulator and not from real machines. The anomaly model has only simulated readings to learn from. Treat what you see in the hosted service as a demonstration of the software until we say otherwise on the website.
:::
:::if not hosted
The software works from end to end but the project is at an early stage. The sensor hardware is designed and not yet built. Every reading the software shows today comes from a simulator and not from real machines. The hosted service is not open yet and nobody has an account on it.
:::

We do not charge for the website{if hosted: or the hosted service}.

## 3. Who may have an account

- Accounts are by invitation. We do not offer public sign-up.
- You must be 18 or over.
- An account is for one person. Do not share it.
- The details you give us must be true. Keep your email address up to date so we can reach you.

We choose who to invite and which role each account has: admin, technician or viewer.

## 4. Looking after your account

- Keep your password to yourself and do not use it anywhere else. We recommend turning on two-step sign-in.
- You are responsible for what is done through your account unless someone got in because of our mistake.
- Tell us straight away at [contact@phaemos.com](mailto:contact@phaemos.com) if you think someone else has used your account or learned your password.
- Keep machine API keys secret. Anyone who has a machine's key can send readings as that machine. If a key may have leaked, ask an admin to replace it. The dashboard has no button for this yet, so an admin replaces it through the API.

## 5. Acceptable use

You may use the website and the hosted service only for their purpose: looking at, running and testing machine monitoring with PHAEMOS.

You must not:

- break the law or help anyone else to break it
- access or try to access an account, a machine or data that you have not been given access to
- get round or try to get round sign-in, roles, rate limits or any other security control
- probe, scan or test the hosted service for weaknesses, except as our [security policy](/security) allows
- upload or send anything that contains a virus or other code meant to cause harm
- send readings, requests or messages in a volume or pattern meant to slow the service down or stop it working for others
- send data to the API except from a sensor node or tool that you are entitled to connect, using a key issued for that machine
- upload firmware that you do not have the right to distribute or that is meant to damage a device
- put personal data about other people into machine names, ticket text or any other free-text field, beyond a colleague's name where the work needs it
- put anything unlawful, defamatory, harassing or obscene into the service or the contact form
- use the contact form, invitations{if brevo:, alert emails or alert texts}{if not brevo: or alert emails} to send unsolicited messages
- copy data out of the hosted service by automated means that we have not agreed to, other than through the export features and the API routes your role allows
- resell the hosted service or offer it to others as your own
- pretend to be us or suggest that we endorse you when we do not.

If you are not sure whether something is allowed, ask us first.

## 6. How these terms relate to the open source licences

PHAEMOS is open source. The software is licensed under the GNU Affero General Public License version 3 or later. The hardware designs are licensed under the CERN Open Hardware Licence version 2, Strongly Reciprocal. The [licensing notice](https://github.com/phaemos/phaemos/blob/main/NOTICE.md) in the repository says which licence covers which part.

Those licences govern the code and the designs. They set out what you may do with them, including running your own copy, changing it and sharing it. These terms govern only your use of the website and the hosted service that we run.

Neither restricts the other. Nothing in these terms takes away a right that a licence gives you over the code or the designs. Nothing in a licence gives you a right to an account on our hosted service or to its availability.

The PHAEMOS name and logo identify this project. Please do not use them in a way that suggests we run or endorse your copy or your product.

## 7. What you put into the hosted service

"Your content" means what you add to the hosted service: machine names and locations, alert rules, ticket text, webhook addresses, firmware files and the readings your nodes send.

- Your content stays yours. We do not claim ownership of it.
- You give us permission to store, copy, process and display your content as far as we need to in order to run, secure, back up and support the hosted service. This permission ends when the content is deleted, apart from backups for the short period set out in the privacy notice.
- You are responsible for your content and for having the right to put it there.
- Other people with an account may see your content according to their role. An admin or a viewer can see every machine. A technician can see their own machines and machines nobody owns.
- You can download your own account data from your profile page. A machine's page saves its last 24 hours of readings as a CSV file and the API's export route covers up to 31 days at a time. Keep your own copy of anything you cannot afford to lose. We take backups to recover the service as a whole and cannot restore one person's content on request.
- Readings are deleted automatically once they are more than 90 days old.
- We may remove content that breaks these terms.

How we handle personal data is explained in the [privacy notice](/privacy). The privacy notice is information for you. It is not part of this contract.

## 8. Hardware, firmware and webhooks

- If we agree that you may connect a sensor node, you are responsible for building, installing and powering it safely and for the machine it is attached to. The hardware designs are published for you to build from at your own risk under their licence.
- If you add a webhook, alerts are sent to the address you give. You are responsible for that address and for whoever receives the messages there.
- If you sign in through {providers}, your use of that provider is under its own terms. {if google|github|microsoft}

## 9. Alerts are an aid, not a safety system

This section matters. Please read it.

PHAEMOS is a monitoring and maintenance planning tool. It is not a safety system and has not been designed, tested or certified as one.

- Do not rely on PHAEMOS to protect people, to stop a machine or to prevent damage.
- PHAEMOS is not a substitute for machine guarding, emergency stops, interlocks, safety-rated control systems, statutory inspections, risk assessments, the manufacturer's maintenance schedule or the judgement of a competent person.
- An alert can be late, wrong or missing. Sensors fail, networks drop, emails {if brevo:and texts }are delayed and the hosted service can be unavailable. {if brevo:A text or }{if not brevo:An }email for the same problem is sent no more than once an hour and there is a daily limit on how many are sent.
- The anomaly model flags readings that look unusual compared with what it has learned. It will flag healthy machines some of the time and it can miss a real fault. No alert does not mean no fault.
- A machine shown as online may no longer be sending readings. Check when it last reported.
- You remain responsible for the safety of your machines, your workplace and the people in it. You also remain responsible for meeting your duties under health and safety law.

## 10. Availability and changes to the service

:::if hosted
We want the hosted service to be available but we do not promise that it will be. It may be interrupted for maintenance, by a fault or by something outside our control. The [status page](/status) shows whether the API is answering.
:::
:::if not hosted
The hosted service is not open yet. The website may be interrupted for maintenance, by a fault or by something outside our control.
:::

The hosted service is still being developed. We may add, change or remove features. We may also stop running it. We will give account holders at least 30 days' notice by email before we stop the service or take away something you rely on, unless we have to act sooner for security or legal reasons.

## 11. Our responsibility to you

We do not exclude or limit our liability where it would be unlawful to do so. In particular, nothing in these terms excludes or limits our liability for:

- death or personal injury caused by our negligence
- fraud or fraudulent misrepresentation
- any other liability that the law does not allow us to exclude or limit.

**If you use the service as a consumer**, which means for purposes wholly or mainly outside your trade, business, craft or profession, you have legal rights under the Consumer Rights Act 2015. They include the right to a service carried out with reasonable care and skill. Nothing in these terms affects those rights. Citizens Advice can tell you more about them. We are responsible for loss or damage you suffer that is a foreseeable result of our breaking these terms or failing to use reasonable care and skill. We are not responsible for loss or damage that is not foreseeable.

**If you use the service in the course of a business, trade or profession**, the rest of this section applies to you:

- We provide the website and the hosted service as they are and as available. Apart from what these terms say, we give no warranty or promise about them, including about their accuracy, their availability or their fitness for a particular purpose. Terms that the law would otherwise imply are excluded as far as the law allows.
- We are not liable for loss of profit, loss of revenue, loss of production, loss of business, business interruption, loss of data, damage to data or any indirect or consequential loss.
- We are not liable for loss or damage that arises from relying on an alert, on the absence of an alert, on a reading or on an anomaly score. Section 9 explains why.
- Our total liability to you for everything else that arises from these terms, the website or the hosted service is limited to £100.

We are not responsible for a failure or delay caused by something outside our reasonable control, such as a failure of a hosting or email provider{if brevo: or a text message provider}.

The open source licences contain their own disclaimers of warranty and liability for the code and the designs. Those apply when you use the code or the designs yourself.

## 12. Suspending and ending an account

You can stop using the hosted service at any time and delete your account from your profile page. The page asks you to prove it is you first and refuses while you own machines or are the last admin. The privacy notice explains what to do then.

We may suspend or close your account if:

- you break these terms in a way that matters
- we need to protect the service, its users or anyone else from harm, for example if your account appears to have been taken over
- the law requires it
- you have not signed in for 12 months
- we stop running the hosted service.

We will tell you by email and give the reason. Where we reasonably can, we will tell you before we act. If we suspend an account over something that can be put right, we will give you the chance to put it right. If you think we got it wrong, reply to that email and we will look at it again.

When an account is closed your access ends. What happens to your data is set out in the [privacy notice](/privacy). Sections 6, 7, 9, 11 and 15 continue to apply after an account ends.

## 13. The website

The website's articles and documentation are there for information. We try to keep them accurate but they may be out of date and they are not professional advice. Links to other sites are for convenience. We are not responsible for those sites.

## 14. Changes to these terms

We may change these terms, for example when the service changes or the law does. The date at the top shows the latest version. If a change is significant we will email account holders at least 14 days before it takes effect. If you do not agree with a change you can delete your account before it takes effect. Using the hosted service after that date means you accept the new terms.

## 15. Other points

- These terms are between you and us. Nobody else has rights under them.
- If a court finds part of these terms invalid, the rest still applies.
- If we do not enforce a term straight away, we can still enforce it later.
- We may transfer our rights and duties under these terms to another organisation that takes over the hosted service. We will tell you if that happens and your rights will not be reduced. You may not transfer your account.

## 16. Law and courts

These terms are governed by the law of England and Wales. The courts of England and Wales will deal with any dispute. If you are a consumer living in Scotland or Northern Ireland you can also bring a claim in your local courts and you keep the protection of the mandatory rules of the law where you live.

## 17. Contact

Questions about these terms go to [contact@phaemos.com](mailto:contact@phaemos.com). For help using PHAEMOS write to [support@phaemos.com](mailto:support@phaemos.com). To report a security problem follow the [security policy](/security).
