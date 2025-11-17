 #!/usr/bin/env bash
  # -*- coding: utf-8 -*-

  password="test123"

  # Email list
  adm_users=(
      "admin0@example.org"
      "admin1@example.org"
      "admin2@example.org"
      "admin3@example.org"
      "admin4@example.org"
      "admin5@example.org"
  )

  users=(
      "user1@example.org"
      "user2@example.org"
      "user3@example.org"
      "user4@example.org"
      "user5@example.org"
  )

  echo "Creating users with password: $password"
  echo "========================================"

  for email in "${adm_users[@]}" "${users[@]}"; do
    echo "Creating user: $email"
    pipenv run invenio users create "$email" --password "$password" --active --confirm
  done

  for email in "${adm_users[@]}"; do
   echo "Promoting user: $email"
   pipenv run invenio access allow administration-access user "$email"
  done

  echo "========================================"
  echo "All users created successfully!"
  echo "Create upload credentials with pipenv run invenio tokens create -n uploader -u admin0@example.org"
