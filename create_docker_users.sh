 #!/usr/bin/env bash
  # -*- coding: utf-8 -*-

  container_name="demo-1-web-api-1"
  password="test123"

  # Email list
  adm_users=(
      "admin1@invenio"
      "admin2@invenio"
      "admin3@invenio"
      "admin4@invenio"
      "admin5@invenio"
  )

  users=(
      "user1@invenio"
      "user2@invenio"
      "user3@invenio"
      "user4@invenio"
      "user5@invenio"
  )

  echo "Creating users with password: $password"
  echo "========================================"

  for email in "${adm_users[@]}" "${users[@]}"; do
    echo "Creating user: $email"
    docker exec -it "$container_name" invenio users create "$email" --password "$password" --active --confirm
  done

  for email in "${adm_users[@]}"; do
   echo "Promoting user: $email"
   docker exec -it "$container_name" invenio access allow administration-access user "$email"
  done

  echo "========================================"
  echo "All users created successfully!"
