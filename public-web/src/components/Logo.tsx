import { useState } from "react";
import { useLogoUrl } from "../lib/theme";

interface Props {
  churchName: string;
  size: "sm" | "lg";
}

/**
 * Church logo from /branding/logo. The large variant also shows the church
 * name underneath, since many logos are a mark without a wordmark. If the
 * image is missing, the name is shown on its own.
 */
export function Logo({ churchName, size }: Props) {
  const [failed, setFailed] = useState(false);
  const src = useLogoUrl();

  if (size === "sm") {
    if (failed) return null;
    return (
      <img
        src={src}
        alt={churchName}
        onError={() => setFailed(true)}
        className="h-9 w-auto max-w-[5.5rem] shrink-0 object-contain"
      />
    );
  }

  return (
    <div className="flex flex-col items-center gap-3">
      {!failed && (
        <img
          src={src}
          alt=""
          onError={() => setFailed(true)}
          className="h-20 w-auto max-w-[16rem] object-contain"
        />
      )}
      {churchName && <span className="font-name text-2xl font-semibold tracking-tight text-gray-900">{churchName}</span>}
    </div>
  );
}
