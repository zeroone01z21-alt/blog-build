---
title: "Pipeline proof — this page is a technical test"
description: "A temporary page published to verify the blog build and deploy pipeline end to end. It is not editorial content and will be removed."
slug: "pipeline-proof"
date: 2026-08-03T10:00:00+03:00
lastmod: 2026-08-03T10:00:00+03:00
draft: false
categories: ["Search Engine Optimization (SEO)"]
featured_image: "cover.jpg"
featured_image_alt: "ZERO 2 ONE"
---

**This is not an article.** It is a temporary page published to prove that the
blog pipeline works before any real writing begins.

## What it verifies

Content is written as Markdown in one repository, a build runs in a second, and
the finished HTML is uploaded to `/blog/` on the live host. Nothing here is
rendered by JavaScript — view the page source and every word below is already
in it.

## What is being checked

- A unique title and meta description
- An absolute canonical URL pointing at this page
- Open Graph and Twitter card tags with a real 1200x630 image
- `BlogPosting` and `BreadcrumbList` structured data bound to the ZERO 2 ONE
  organisation entity already defined on the main site
- Reciprocal `hreflang` between the English and Arabic versions

This page will be deleted once the checks pass.
