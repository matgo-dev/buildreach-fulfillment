"use client";

import { CSSProperties, ComponentProps, useEffect, useState } from "react";
import { Image } from "antd";

import { authFetch } from "@/lib/api";
import { imageUrl } from "@/lib/image";
import { colors } from "@/lib/tokens";

type AntImageProps = ComponentProps<typeof Image>;

type AuthenticatedImageProps = Omit<AntImageProps, "src"> & {
  imageKey: string | null | undefined;
};

const TRANSPARENT_PIXEL =
  "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==";

function boxStyle(width: AntImageProps["width"], height: AntImageProps["height"], style?: CSSProperties) {
  return {
    width,
    height,
    background: colors.bg,
    ...style,
  };
}

export function AuthenticatedImage({ imageKey, alt = "", preview, style, width, height, ...rest }: AuthenticatedImageProps) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let revoked = false;
    let objectUrl: string | null = null;

    setSrc(null);
    setFailed(false);
    if (!imageKey) return undefined;

    authFetch(imageUrl(imageKey))
      .then(async (res) => {
        if (!res.ok) throw new Error(`Image request failed: ${res.status}`);
        const blob = await res.blob();
        if (revoked) return;
        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
      })
      .catch(() => {
        if (!revoked) setFailed(true);
      });

    return () => {
      revoked = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [imageKey]);

  if (!imageKey || failed) {
    return <div aria-label={alt} style={boxStyle(width, height, style)} />;
  }

  return (
    <Image
      {...rest}
      alt={alt}
      width={width}
      height={height}
      src={src ?? TRANSPARENT_PIXEL}
      preview={src ? preview : false}
      style={boxStyle(width, height, style)}
    />
  );
}
