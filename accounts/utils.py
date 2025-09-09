def get_domain_from_email(email: str) -> str:
    """
    Return the effective domain (registrable domain) from an email address.

    This is a lightweight heuristic: by default it returns the last two labels
    from the host part of the email. For a
    small set of common multi-part public suffixes (e.g. 'co.uk', 'co.in') it
    returns the last three labels so 'user@dept.example.co.uk' -> 'example.co.uk'.

    It lower-cases the result and returns an empty string for invalid input.
    """
    if not email or "@" not in email:
        return ""

    email = email.strip().lower()
    try:
        _local, host = email.rsplit("@", 1)
    except ValueError:
        return ""

    # remove any port-like suffix (unlikely in emails, but safe)
    host = host.split(":", 1)[0].strip()
    if not host:
        return ""

    labels = [lbl for lbl in host.split(".") if lbl]
    if not labels:
        return ""

    # Common second-level public suffixes where the registrable domain
    # includes three labels (e.g. example.co.uk -> example.co.uk)
    three_label_suffixes = {
        "co.uk",
        "gov.uk",
        "ac.uk",
        "org.uk",
        "co.in",
        "org.in",
        "net.in",
        "ac.in",
        "gov.in",
    }

    if len(labels) >= 3 and ".".join(labels[-2:]) in three_label_suffixes:
        return ".".join(labels[-3:])

    if len(labels) >= 2:
        return ".".join(labels[-2:])

    # single-label host (rare) - return as-is
    return labels[0]

