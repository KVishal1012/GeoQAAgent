-- Allow browser resumable uploads only into generated GeoQA upload folders.
-- Artifacts remain private and service-role only.

drop policy if exists geoqa_uploads_anon_insert_upload_prefix on storage.objects;
drop policy if exists geoqa_uploads_anon_select_upload_prefix on storage.objects;
drop policy if exists geoqa_uploads_anon_update_upload_prefix on storage.objects;

create policy geoqa_uploads_anon_insert_upload_prefix
on storage.objects
for insert
to anon
with check (
  bucket_id = 'geoqa-uploads'
  and (storage.foldername(name))[1] like 'upload-%'
);

create policy geoqa_uploads_anon_select_upload_prefix
on storage.objects
for select
to anon
using (
  bucket_id = 'geoqa-uploads'
  and (storage.foldername(name))[1] like 'upload-%'
);

create policy geoqa_uploads_anon_update_upload_prefix
on storage.objects
for update
to anon
using (
  bucket_id = 'geoqa-uploads'
  and (storage.foldername(name))[1] like 'upload-%'
)
with check (
  bucket_id = 'geoqa-uploads'
  and (storage.foldername(name))[1] like 'upload-%'
);
