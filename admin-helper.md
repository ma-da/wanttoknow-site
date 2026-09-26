# WantToKnow.info Admin Helper

This guide is for the WantToKnow.info editorial/admin team. It explains the normal weekly workflow and how to use the production admin tools for articles, images, publishing, newsletters, feedback, and basic site analytics.

> **Important:** Work in the admin area is live production work. Use **Save Draft** freely while editing. Use **Publish** only when the content is ready to go live.

---

## 1. Weekly Editorial Workflow

The normal weekly article/newsletter workflow is:

### 1. Amber adds new articles

For each article, Amber enters:

- **Article title**
- **Source URL**
- **Optional WTK Note**

Schedule:

- At least **4 articles should be added by Tuesday afternoon**.
- The rest of the week's articles should be added by **Thursday afternoon**.

New articles appear in **Drafts** after they are created.

### 2. Amber adds ratings and images

Amber reviews all draft articles and adds:

- the appropriate **rating / priority**
- an **article image** where appropriate
- any needed publication/category information

Ideally, this work is complete by **Saturday**.

### 3. Mark completes the summaries

Mark writes or finalizes the **summary** for each article before **Sunday**.

The **WTK Note** can also be edited at this stage if needed.

### 4. Mark creates the draft newsletter

Mark:

- adds draft newsletter headlines
- selects and orders the week's regular and inspiring articles
- adds preview text and any special note
- saves the newsletter draft

### 5. Amber finalizes and sends the newsletter

Amber opens the **Newsletter Editor** and:

- reviews the complete newsletter
- adjusts newsletter text
- edits article summaries or WTK Notes if needed
- reviews the live styled preview
- saves/publishes any article changes
- exports the final newsletter HTML
- sends the newsletter to the email list

---

# 2. Admin Area Overview

The admin area currently includes:

- **Articles** — search, create, edit, review, and publish articles
- **Drafts** — articles with unpublished changes
- **Article images** — upload and stage article images
- **Newsletter Builder** — assemble newsletter issues
- **Newsletter Editor** — edit the complete newsletter with Markdown and a live styled preview
- **Feedback** — review contact messages and site survey responses
- **Recent Visits / Analytics** — view recent page activity and visit totals

The article editor is the canonical editing interface for article content. The newsletter editor can also edit article summaries and WTK Notes, but those edits are saved back into the same article system.

---

# 3. Articles

## Creating a New Article

From the Articles admin page, choose the option to create/add a new article.

Enter:

1. **Title**
2. **Source URL**
3. **Optional WTK Note**

Save/create the article.

A new article receives an article ID and appears as a **Draft**.

At this stage the article is not yet public.

---

## Finding Articles

Use the Articles page to search and filter existing records.

Useful ways to find an article include:

- title
- article ID
- publication
- category/tag
- draft/published state

Use the Drafts view when working through the current week's unpublished material.

---

## Editing an Article

Open an article to edit its complete record.

Common fields include:

### Title

The headline used on the WantToKnow.info article page.

### Source URL

The original source article URL.

For new articles, this should be a valid `http://` or `https://` URL.

### Publication

Choose the canonical publication/source when available.

If a publication is missing from the available list, use the admin's publication controls rather than inventing slightly different spellings of an existing publication.

### Publication Date

The date the source article was originally published.

### WTK Posted Date

The date the article is published on WantToKnow.info.

If a new article is published with this field blank, the publication process can assign the current date automatically.

### Rating / Priority

Use the team's current editorial rating/priority system.

This value is used to help order and prioritize articles in the archive and admin workflow.

### Summary

The main WantToKnow.info summary.

Markdown is supported.

### WTK Note

Optional commentary, context, related links, or editorial framing shown separately from the main summary.

Markdown is supported.

### Categories / Tags

Select the categories that best describe the article.

Use existing categories wherever possible.

### Image

Upload the image intended for the article.

The admin processes the image and stages it for publication.

---

# 4. Save Draft vs. Publish

This distinction is important.

## Save Draft

**Save Draft** saves your current edits into the admin working state.

Use it frequently.

Saving a draft:

- preserves your work
- does not make the article public
- allows another admin to continue editing
- records the article as having unpublished changes

An article can remain in Drafts until it is ready.

## Publish

**Publish** makes the selected article changes live.

The publication process validates the article and rebuilds the necessary article/site outputs.

Article image changes are also promoted from staging when publication succeeds.

Git synchronization happens as part of the publication workflow but should not be treated as the editorial action itself. If the admin reports a Git synchronization warning after the article has otherwise published successfully, report the warning to Mark rather than republishing or undoing the article.

---

# 5. Publishing Multiple Draft Articles

The Articles admin supports publishing selected draft articles.

Use the checkboxes to select only the drafts that are actually ready.

Before publishing, review each selected article for:

- title
- source URL
- publication
- publication date
- rating/priority
- summary
- WTK Note
- categories
- image

Then choose **Publish selected**.

Only the selected drafts should be published. Unselected drafts remain in Drafts.

Do not select unfinished articles simply because they are part of the same week's batch.

---

# 6. Article Images

Images uploaded through the article editor are staged privately until publication.

Normal flow:

1. Open the article.
2. Upload/select the desired image.
3. Confirm the preview looks correct.
4. Save the article.
5. Publish the article when all content is ready.

The public image is updated as part of the article publication process.

If an image needs to be replaced, upload the replacement through the article editor rather than manually changing site files.

---

# 7. Deleting or Withdrawing Articles

## New, Never-Published Draft

A brand-new draft that has never been published can be deleted through the admin when appropriate.

Use this only for accidental or unwanted new drafts.

## Previously Published Article

Do not delete a previously published article as though it were a new draft.

Use the article withdrawal/removal workflow instead.

This preserves the article's history and allows the system to handle the public URL appropriately.

If there is any uncertainty about whether an article should be withdrawn, check with Mark before proceeding.

---

# 8. Newsletter Builder

Open **Newsletter** from the admin navigation.

The Newsletter Builder is used to assemble an issue before final editing.

## Open an Existing Draft

Use **Open newsletter draft** to select an existing issue.

## Issue Date

Choose the date of the newsletter.

## Page Title

Enter the newsletter title.

## Three Headlines

Enter the three primary newsletter headlines.

These are used in the newsletter presentation and metadata.

## Regular Preview Items

Enter the short introductory bullets for the regular-news section, one item per line.

## Regular Articles

Use the Article Picker to find articles and add them to the **Regular articles** section.

Articles can be reordered.

## Inspiring Preview Items

Enter the introductory bullets for the inspiring section, one item per line.

## Inspiring Articles

Add inspiring articles to the **Inspiring articles** section.

Articles can be reordered.

## Special Note

Use this for newsletter-specific commentary or announcements.

Markdown is supported.

---

## Newsletter Builder Top Controls

### Back to Articles

Returns to the article admin.

### Open Editor

Saves the current newsletter draft and opens the full Newsletter Editor.

### Save Draft

Saves the current newsletter issue without exporting or sending it.

### Full Page Preview

Opens the rendered newsletter for review.

### Download HTML

Exports the rendered newsletter as an HTML file for the email platform.

### Trash

Deletes the newsletter draft.

Use this carefully. Deleting the newsletter draft is different from deleting any articles contained in it.

---

# 9. Opening Articles from the Newsletter

Article titles in the Newsletter Builder are links.

Click an article title to open that article's normal editor in a new tab.

Use this whenever you need to change fields other than the summary or WTK Note.

Examples:

- title
- source URL
- publication
- date
- rating/priority
- categories
- image

---

# 10. Newsletter Editor

The Newsletter Editor is the final editing workspace.

The page contains:

- one top control bar
- the newsletter template selector
- status messages
- **Markdown editor on the left**
- **live styled preview on the right**

The standard newsletter template is labeled:

**Standard News Template**

Additional newsletter templates may be added later for things such as funding appeals or investigations.

---

## Editing the Newsletter

The left side contains the complete editable newsletter document.

The right side shows the rendered newsletter using the actual newsletter template.

As you edit the Markdown, the preview updates automatically.

Use this editor for final proofreading, wording adjustments, headline work, summaries, notes, and newsletter-specific text.

---

## Article Summary and WTK Note Blocks

Each included article contains editable blocks for:

- **Summary**
- **WTK Note**

Changes made here are changes to the canonical article record, not just temporary newsletter text.

That means a summary or note corrected in the Newsletter Editor will also be corrected in the article admin after it is saved.

### Article Titles

Article titles shown inside the Newsletter Editor are reference information.

If a title itself needs to change, open the article in the normal article editor.

---

## Protected WTK Markers

The Newsletter Editor uses invisible Markdown comments similar to:

```markdown
<!-- WTK:ARTICLE 14650 SUMMARY START -->
...
<!-- WTK:ARTICLE 14650 SUMMARY END -->
```

and:

```markdown
<!-- WTK:ARTICLE 14650 NOTE START -->
...
<!-- WTK:ARTICLE 14650 NOTE END -->
```

These markers tell the admin exactly where newsletter fields and article fields begin and end.

**Do not delete, rename, reorder, or rewrite the WTK marker lines.**

Edit the content between the markers.

If a marker is accidentally damaged, reload the editor before saving and redo the text edit.

---

# 11. Saving and Publishing from the Newsletter Editor

## Save Draft

Use **Save Draft** while finalizing the newsletter.

It saves:

- newsletter-specific changes to the newsletter draft
- changed article summaries back to those article drafts
- changed WTK Notes back to those article drafts

Article changes saved this way are not automatically made public.

This is the safest button to use while editing.

---

## Save + Publish Article Changes

Use **Save + Publish Article Changes** when the article summary/note edits made in the newsletter are final and should become public.

This action:

1. saves the newsletter
2. saves the changed article fields
3. publishes the eligible changed articles

The newsletter itself is **not emailed** by this button.

It only publishes article changes.

If the system detects unrelated unpublished changes to an article, it may refuse to automatically publish that article. This is a safety feature intended to prevent unrelated work from being published accidentally.

Review the status message before continuing.

---

# 12. Final Newsletter Review and Export

Before sending a newsletter:

1. Review the left-side Markdown.
2. Review the full styled preview on the right.
3. Check every headline.
4. Check article order.
5. Check summaries and WTK Notes.
6. Check links.
7. Check the inspiring section.
8. Check any Special Note.
9. Save final changes.
10. Publish any article changes that should be live.
11. Return to the Newsletter Builder if needed.
12. Use **Download HTML** to export the final email.
13. Import/use the HTML in the email service.
14. Perform the normal email-platform preview/test.
15. Send to the email list.

The newsletter admin does not itself send the mailing.

---

# 13. Newsletter Templates

The Newsletter Editor is designed to support more than one newsletter style.

The current standard option is:

**Standard News Template**

Future templates can support formats such as:

- funding appeals
- investigations
- special announcements

The same editor can be used with those templates while retaining the Markdown + live preview workflow.

When alternate templates become available, choose the appropriate template from the dropdown before final review/export.

---

# 14. Feedback

Open **Feedback** from the admin navigation.

The feedback area is intended for reviewing incoming community responses.

It includes:

- **Contact Messages**
- **Site Survey**
- search/filtering controls
- archived items
- recent page-visit information

## Contact Messages

Use this tab to review messages submitted through the site's contact form.

## Site Survey

Use this tab to review survey feedback submitted by visitors.

## Search

Use the search box to locate relevant responses.

## Archive

Archiving removes a response from the normal working view without treating it as though the original visitor submission never existed.

Use Archived view/filter when you need to find previously archived responses.

---

# 15. Recent Visits / Analytics

The Feedback/admin area also displays lightweight site-visit information.

This may include:

- recent pages visited
- daily counts
- total page counts
- overall visit totals

These numbers are intended as a quick operational view, not a full marketing analytics platform.

Use them to see what parts of the site visitors are using and to identify unusual activity or unexpectedly popular pages.

---

# 16. Markdown Cheat Sheet

Markdown is used in article summaries, WTK Notes, newsletter notes, and the Newsletter Editor.

## Paragraphs

Leave a blank line between paragraphs.

```markdown
First paragraph.

Second paragraph.
```

## Bold

```markdown
**bold text**
```

Result: **bold text**

## Italic

```markdown
*italic text*
```

Result: *italic text*

## Link

```markdown
[WantToKnow.info](https://www.wanttoknow.info/)
```

## Bulleted List

```markdown
- First item
- Second item
- Third item
```

## Numbered List

```markdown
1. First item
2. Second item
3. Third item
```

## Headings

```markdown
## Main section

### Smaller section
```

Use headings sparingly inside summaries and newsletter content.

## Blockquote

```markdown
> Quoted or highlighted text
```

## Horizontal Rule

```markdown
---
```

## Literal Markdown Characters

If punctuation is unexpectedly being interpreted as Markdown, a backslash can usually escape it:

```markdown
\*
\#
\_
```

### Newsletter Editor Reminder

Lines beginning with:

```markdown
<!-- WTK:
```

are system markers.

**Never edit or delete these marker lines.**

---

# 17. Production Safety Rules

A few habits prevent most admin mistakes:

1. **Save Draft often.**
2. **Publish only finished articles.**
3. When publishing multiple articles, select only the articles that are ready.
4. Treat article-summary and WTK Note edits in the Newsletter Editor as real article edits.
5. Do not remove protected WTK markers.
6. Use the normal article editor for article titles, URLs, publications, dates, categories, ratings, and images.
7. Use withdrawal rather than deletion for previously published articles.
8. Review newsletter status messages after saving or publishing.
9. Preview the newsletter before exporting.
10. Test the final HTML in the email platform before sending.
11. If the admin reports a conflict or safety warning, do not repeatedly click Publish. Review the affected article first.
12. If anything looks unexpectedly different after saving, stop and check with Mark before making additional changes.

---

# 18. Quick Weekly Checklist

## Amber — Tuesday

- [ ] Add at least 4 candidate articles
- [ ] Enter title
- [ ] Enter source URL
- [ ] Add optional WTK Note
- [ ] Confirm articles appear in Drafts

## Amber — Thursday

- [ ] Add the remaining articles for the week

## Amber — By Saturday

- [ ] Review every draft
- [ ] Add rating/priority
- [ ] Add images
- [ ] Check publication/category information
- [ ] Add or refine WTK Notes as needed

## Mark — Before Sunday

- [ ] Complete article summaries
- [ ] Review article content
- [ ] Add draft newsletter headlines
- [ ] Create newsletter draft
- [ ] Select/order Regular articles
- [ ] Select/order Inspiring articles
- [ ] Add preview items
- [ ] Add Special Note if needed

## Amber — Final Newsletter

- [ ] Open Newsletter Editor
- [ ] Review complete newsletter
- [ ] Finalize headlines
- [ ] Finalize summaries
- [ ] Finalize WTK Notes
- [ ] Review live styled preview
- [ ] Save Draft
- [ ] Publish final article changes
- [ ] Download HTML
- [ ] Preview/test in email platform
- [ ] Send to email list

---

# 19. When Something Goes Wrong

## A save fails

Read the status message first. Do not refresh immediately if there is unsaved text you can still copy.

## A publish fails

The article should remain in Drafts unless publication completed successfully.

Review the error/status message and the article before trying again.

## The Newsletter Editor reports a conflict

Another save may have changed the newsletter or article after the editor was opened.

Reload the latest version and reapply the intended edit rather than overwriting newer work.

## An article is missing from the newsletter

Return to the Newsletter Builder, search for the article, add it to the correct section, and save.

## The live preview looks wrong

Check the Markdown on the left first, especially:

- blank lines
- malformed links
- accidentally removed WTK markers
- unexpected heading/list syntax

## Unsure whether something is live

Open the public article/page in a separate browser tab and verify it directly.

---

*WantToKnow.info / PEERS — Admin Team Guide*
