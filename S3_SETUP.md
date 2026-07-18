# Connecting Your Render-Hosted ScootyBazaar to AWS S3

Your Flask app is currently saving uploads to `static/images/` on Render's
disk. **Render's disk is ephemeral** — every time the service restarts or
redeploys, anything uploaded after your last `git push` is wiped. That's
why new admin/vendor product images keep disappearing.

This guide walks you through:
1. Creating an S3 bucket
2. Creating an IAM user with limited permissions for that bucket
3. Making the bucket publicly readable (so `<img>` tags work)
4. Setting environment variables in Render
5. Re-deploying

The code in this updated zip is **already wired for S3**. It auto-detects
the env vars: if `AWS_S3_BUCKET` is set, uploads go to S3; otherwise it
falls back to local disk (so dev still works without AWS).

---

## Part 1 — AWS console setup

### Step 1. Create the S3 bucket

1. Sign in to https://console.aws.amazon.com/s3/
2. Click **Create bucket**.
3. **Bucket name**: pick a globally unique name, e.g.
   `scootybazaar-images-prod`. Lowercase, no spaces, hyphens OK.
4. **AWS Region**: pick **Asia Pacific (Mumbai) ap-south-1** (closest to
   your users in Delhi → fastest image loads).
5. **Object Ownership**: leave the default (**ACLs disabled, Bucket owner
   enforced**). Modern best practice.
6. **Block Public Access settings**: **uncheck "Block all public access"**
   and tick the acknowledgement box. Your product images need to be
   readable by browsers, so this is correct. (Bucket policy in step 3
   will only allow *read*, never write/list.)
7. Leave versioning, encryption, and other settings at defaults.
8. Click **Create bucket**.

### Step 2. Add a bucket policy for public read

1. Open your new bucket → **Permissions** tab → scroll to **Bucket
   policy** → **Edit**.
2. Paste this, replacing `YOUR-BUCKET-NAME`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadProductImages",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/products/*"
    }
  ]
}
```

This allows anyone to **read** files under `products/` (which is where
the app uploads them) but does not allow listing, writing, or deleting.

3. Click **Save changes**.

### Step 3. Configure CORS (only if you ever upload directly from the browser)

The current Flask code uploads server-side (browser → Flask → S3), so
you do **not** need CORS. Skip this step. Only set CORS if you later
move to direct browser-to-S3 uploads.

### Step 4. Create an IAM user with write access

You need access keys for your Flask app to put objects into the bucket.
Never use your root account keys.

1. Go to https://console.aws.amazon.com/iam/
2. Left sidebar → **Users** → **Create user**.
3. **User name**: `scootybazaar-app`
4. **Do not** check "Provide user access to the AWS Management Console".
5. Click **Next** → on the permissions page choose **Attach policies
   directly** → click **Create policy** (opens new tab).

In the new tab, click the **JSON** tab and paste (replace bucket name):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AppBucketAccess",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/products/*"
    }
  ]
}
```

6. Click **Next**, name the policy `ScootyBazaarS3Access`, **Create
   policy**.
7. Back in the user creation tab, click the refresh icon next to the
   policy list, search `ScootyBazaarS3Access`, tick it, **Next**, then
   **Create user**.

### Step 5. Generate access keys

1. Click into the new `scootybazaar-app` user.
2. **Security credentials** tab → **Access keys** → **Create access key**.
3. Use case: **Application running outside AWS**. Tick the confirmation
   → **Next** → **Create access key**.
4. **Copy both values right now**:
   - `Access key ID` — looks like `AKIA...`
   - `Secret access key` — long random string. **You can't view this
     again after closing this page** — if you lose it, delete the key
     and make a new one.

---

## Part 2 — Render setup

### Step 6. Add environment variables on Render

1. Go to https://dashboard.render.com/, open your ScootyBazaar service.
2. Left sidebar → **Environment**.
3. Add these key-value pairs:

| Key                     | Value                                |
| ----------------------- | ------------------------------------ |
| `AWS_S3_BUCKET`         | `your-bucket-name` (from step 1)     |
| `AWS_S3_REGION`         | `ap-south-1`                         |
| `AWS_ACCESS_KEY_ID`     | `AKIA...` (from step 5)              |
| `AWS_SECRET_ACCESS_KEY` | the long secret (from step 5)        |

4. Click **Save Changes**. Render will auto-redeploy.

### Step 7. Push the updated code

The updated zip already has S3 wiring. From your local machine, in your
project folder:

```bash
git add app.py requirements.txt templates/
git commit -m "Add S3 storage for product images"
git push
```

Render will redeploy automatically (or trigger a manual deploy from the
Render dashboard).

### Step 8. Verify it's working

1. Wait for the deploy to finish (watch Render's **Logs** tab).
2. In the logs, look for this line near the top:
   ```
   [S3] Enabled - bucket=your-bucket-name region=ap-south-1
   ```
   If you see `[S3] AWS_S3_BUCKET not set` instead, your env vars
   didn't save — re-check step 6.
3. Open your live site → log in as admin → upload a new product image.
4. After the redirect, right-click the image → **Inspect**. The `<img
   src=...>` should now look like
   `https://your-bucket-name.s3.ap-south-1.amazonaws.com/products/...`
   instead of `/static/images/...`.
5. Now redeploy / restart your Render service from the dashboard. The
   image **should still be there** — that's the whole point.

---

## Troubleshooting

**`AccessDenied` errors in Render logs when uploading**
The IAM user policy is wrong or pointed at the wrong bucket name.
Re-check step 4. The `Resource` ARN must exactly match
`arn:aws:s3:::YOUR-BUCKET-NAME/products/*`.

**Images upload but show as broken in the browser**
The bucket policy from step 2 isn't applied or has the wrong bucket
name. In the S3 console, click the uploaded object → **Object URL** —
opening that URL in a new tab should display the image. If it shows an
XML `AccessDenied`, the bucket policy is missing or wrong.

**Old (seed) images like `scooter_red.png` still work, new ones don't**
That's normal during the transition — old images are bundled in your
git repo's `static/images/` folder and are served by Flask directly.
Only newly uploaded ones go to S3. The `image_url()` helper in
`app.py` handles both transparently.

**Bill anxiety**
S3 storage is essentially free at your scale. The Mumbai region costs
around 2.3 cents per GB-month for storage and bandwidth runs about 9
cents per GB out. A few thousand product images = pennies per month.
Set up a billing alert at https://console.aws.amazon.com/billing/ if
you want peace of mind.

---

## What if I want a CDN later?

When traffic grows, put CloudFront in front of the bucket and set the
`AWS_S3_PUBLIC_URL` env var to your CloudFront URL (e.g.
`https://d1abc123.cloudfront.net`). The app will start writing those
URLs into the DB and serving images via CloudFront automatically. No
code change needed.

---

## What changed in the code?

For reference, the differences from your original zip:

- **`requirements.txt`** — added `boto3==1.34.144`
- **`app.py`** — added an S3 storage layer at the top, an
  `image_url()` Jinja helper, and S3-aware upload/delete logic in
  `_collect_product_form` and the image-delete routes. Falls back to
  local disk when S3 env vars aren't set.
- **5 templates** (`_product_card.html`, `product_detail.html`,
  `product_form.html`, `admin_dashboard.html`, `vendor_dashboard.html`)
  — switched from `url_for('static', filename='images/' + x)` to
  `image_url(x)` so they handle both local filenames and full S3 URLs.

The DB schema is unchanged. Old data continues to work.
