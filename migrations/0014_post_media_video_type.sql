-- Allow video media type in addition to image
ALTER TABLE post_media DROP CONSTRAINT post_media_type_check;
ALTER TABLE post_media ADD CONSTRAINT post_media_type_check CHECK (media_type IN ('image', 'video'));
